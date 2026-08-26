"""Delivering a notification to Telegram.

The missing half of the notification engine. `TelegramChannel` has existed
since notifications were written, with tests, and nothing in the project ever
constructed it - so `sync_scope.channels` returned the in-app inbox alone and
every notification the platform has ever produced went only there. A broadcast
reported "sent 2/2" and reached nobody's phone, an expiry reminder warned
nobody, and an approved payment told the customer nothing.

Two adapters, both small, because the hard part was never the code:

* **The sender speaks HTTP, not aiogram.** The scope that owns notifications is
  synchronous and lives in the API and worker processes; aiogram's client is
  asynchronous and belongs to the bot. One `POST /sendMessage` needs neither,
  and keeping it to httpx means the API does not grow a bot framework to send a
  sentence.
* **The resolver is the identity.** Every integer id in the synchronous half -
  wallets, payments, subscriptions, audiences, `admin_actor_id` - is already a
  Telegram id. The port exists so the domain never has to know that; this is
  where the knowledge is allowed to live.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from geekvpn.application.notifications.sticker_sections import SECTION_EMOJI
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

#: Long enough for a slow route out of Iran, short enough that a broadcast to a
#: few thousand people cannot wedge a worker for an afternoon.
TIMEOUT_SECONDS = 10.0


class TelegramApiError(RuntimeError):
    """A refusal from the Bot API, carrying the description verbatim.

    Verbatim on purpose: `TelegramChannel` matches "bot was blocked" and
    "chat not found" in the text to tell a customer who left from a delivery
    that broke, and suppressing one as a failure would have the platform
    retrying somebody who blocked the bot.
    """


class HttpTelegramSender:
    """`TelegramSender` over the Bot API."""

    def __init__(self, token: str, *, parse_mode: str = "HTML", sticker_set: str = "") -> None:
        self._token = token
        self._parse_mode = parse_mode
        self._sticker_set = sticker_set.strip()
        self._pack: dict[str, str] | None = None

    def send_section_sticker(self, *, chat_id: int, section: str) -> None:
        """A duck in front of good news.

        The bot has its own copy of this because it decorates screens; this one
        exists because an approved payment and a delivered service are pushed
        from the API and worker processes, where there is no bot to ask.

        Best effort throughout, and the caller treats a raised exception as a
        missing decoration rather than a failed delivery. Nothing here may cost
        somebody the message saying their money arrived.
        """
        file_id = self._sticker_for(section)
        if not file_id:
            return
        httpx.post(
            f"https://api.telegram.org/bot{self._token}/sendSticker",
            json={"chat_id": chat_id, "sticker": file_id},
            timeout=TIMEOUT_SECONDS,
        )

    def _sticker_for(self, section: str) -> str:
        for emoji in SECTION_EMOJI.get(section, ()):
            found = self._loaded().get(emoji)
            if found:
                return found
        return ""

    def _loaded(self) -> dict[str, str]:
        """The pack, read once per process.

        Cached even on failure: a wrong name would otherwise be one doomed
        Telegram call for every notification the platform sends.
        """
        if self._pack is not None:
            return self._pack

        self._pack = {}
        if not self._sticker_set:
            return self._pack

        try:
            response = httpx.get(
                f"https://api.telegram.org/bot{self._token}/getStickerSet",
                params={"name": self._sticker_set},
                timeout=TIMEOUT_SECONDS,
            )
            stickers = response.json()["result"]["stickers"]
        except Exception:
            logger.info("notify.stickers_unavailable", set_name=self._sticker_set)
            return self._pack

        for sticker in stickers:
            emoji = sticker.get("emoji")
            # First wins: packs repeat emoji, and the earlier one is usually
            # the plainer drawing.
            if emoji and emoji not in self._pack:
                self._pack[emoji] = sticker["file_id"]
        logger.info(
            "notify.stickers_loaded", set_name=self._sticker_set, emoji=len(self._pack)
        )
        return self._pack

    def send_message(self, *, chat_id: int, text: str, action: str | None = None) -> None:
        # `action` is a logical destination the bot turns into a button. A
        # button needs a callback the bot process owns, so it is deliberately
        # not rendered here: a broken button is worse than none, and the text
        # already says what happened.
        response = httpx.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": self._parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT_SECONDS,
        )

        if response.status_code == httpx.codes.OK:
            return

        description = ""
        try:
            description = str(response.json().get("description", ""))
        except ValueError:  # pragma: no cover - a gateway page, not JSON
            description = response.text[:200]

        logger.info(
            "notify.telegram.refused",
            status=response.status_code,
            description=description,
        )
        raise TelegramApiError(description or f"HTTP {response.status_code}")


class HttpOperatorSender:
    """`OperatorSender` over the Bot API.

    Separate from `HttpTelegramSender` because the two send different things:
    that one renders a customer template as text, this one sends an image with
    the decisions attached. Buttons arrive as (label, callback data) pairs, so
    the application layer never touches an aiogram type.

    The callback data must match what the bot's operator handlers parse. It is
    built from `AdminCB`'s prefix and the same action names, and there is a
    test holding the two together - a button whose callback nothing decodes is
    a button that answers "this button is from an older version".
    """

    def __init__(self, token: str, *, parse_mode: str = "HTML") -> None:
        self._token = token
        self._parse_mode = parse_mode

    def send_photo(
        self,
        *,
        chat_id: int,
        file_id: str,
        caption: str,
        buttons: Sequence[tuple[str, str]],
    ) -> None:
        self._post(
            "sendPhoto",
            {
                "chat_id": chat_id,
                "photo": file_id,
                "caption": caption,
                "parse_mode": self._parse_mode,
                "reply_markup": _markup(buttons),
            },
        )

    def send_text(
        self, *, chat_id: int, text: str, buttons: Sequence[tuple[str, str]]
    ) -> None:
        self._post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": self._parse_mode,
                "disable_web_page_preview": True,
                "reply_markup": _markup(buttons),
            },
        )

    def _post(self, method: str, payload: dict[str, Any]) -> None:
        response = httpx.post(
            f"https://api.telegram.org/bot{self._token}/{method}",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code == httpx.codes.OK:
            return

        description = ""
        try:
            description = str(response.json().get("description", ""))
        except ValueError:  # pragma: no cover - a gateway page, not JSON
            description = response.text[:200]
        logger.info("notify.operator.refused", method=method, description=description)
        raise TelegramApiError(description or f"HTTP {response.status_code}")


def _markup(buttons: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Approve and reject side by side, green and red.

    The colours are the same ones the operator area uses for the same two
    decisions, because this message is that screen arriving unprompted.
    """
    styles = ("success", "danger")
    return {
        "inline_keyboard": [
            [
                {"text": label, "callback_data": data, "style": style}
                for (label, data), style in zip(buttons, styles, strict=False)
            ]
        ]
    }


class TelegramIdIsTheUserId:
    """`ChatIdResolver` for a system whose user ids are Telegram ids.

    Not a placeholder. The synchronous half stores `user_id` as a `BigInteger`
    holding the Telegram id - see `audiences.py`, which selects
    `UserModel.telegram_id` as the audience - so there is nothing to look up.
    Writing a query that reads a column back to itself would only invite the
    belief that the two id spaces differ.
    """

    def telegram_id(self, user_id: int) -> int | None:
        return user_id or None
