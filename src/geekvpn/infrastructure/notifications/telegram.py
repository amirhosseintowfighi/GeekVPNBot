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

import httpx

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

    def __init__(self, token: str, *, parse_mode: str = "HTML") -> None:
        self._token = token
        self._parse_mode = parse_mode

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
