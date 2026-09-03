"""Making customers join the shop's channels before the bot serves them.

The membership question goes to Telegram, which is why this lives here rather
than in the application layer - the rule itself is `missing_channels`, and it
is a pure function tested without any of this.

Three things are worth reading before changing it.

**A channel we cannot check never blocks anybody.** Telegram refuses
`getChatMember` when the bot is not an administrator of the channel, and errors
when the channel is gone. Treating either as "not joined" would lock every
customer out of a working shop over a misconfiguration only the operator can
see - so the requirement is dropped, loudly in the log.

**Only a pass is cached.** Somebody who has joined is still joined a minute
later, and asking Telegram on every tap is a round trip per channel per button.
Somebody who has *not* joined is about to, and caching that would leave them
staring at a gate they had already satisfied.

**The recheck button is never gated**, or pressing it could not get them out.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, TelegramObject

from geekvpn.application.platform.channel_gate import RequiredChannel, missing_channels
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T

logger = get_logger("bot.channel_gate")

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

#: How long a confirmed membership is trusted. Long enough that tapping through
#: a menu costs nothing, short enough that somebody who leaves the channel is
#: asked again the same session.
PASS_TTL_SECONDS = 300

#: The callback that re-runs the check. Never gated, or it could not release
#: anybody.
RECHECK = "gate:recheck"

#: Telegram's words for somebody who is not in the chat. Anything else - member,
#: administrator, creator, restricted-but-present - counts as joined.
_ABSENT = {"left", "kicked"}


class ChannelGateMiddleware(BaseMiddleware):
    """Refuses everything except the gate itself until the channels are joined."""

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        scope = data.get("scope")
        user = data.get("user")
        bot = data.get("bot")
        cache = data.get("cache")
        telegram_id = getattr(user, "telegram_id", None)

        if scope is None or telegram_id is None or bot is None:
            # No identity yet, or a suspended account already being turned
            # away. Not ours to decide.
            return await handler(event, data)

        if _is_recheck(event):
            # Fall through to the handler, which runs the check itself and
            # either opens the bot or redraws the gate.
            return await handler(event, data)

        missing = await unjoined(scope, bot, telegram_id, cache=cache)
        if not missing:
            return await handler(event, data)

        await _show_gate(event, missing)
        return None


async def unjoined(
    scope: Any, bot: Any, telegram_id: int, *, cache: Any = None
) -> list[RequiredChannel]:
    """The channels this customer still has to join, for this shop."""
    channels = await scope.required_channels.active()
    if not channels:
        return []

    key = f"gate:{telegram_id}:{len(channels)}"
    if cache is not None and await cache.get(key) == "1":
        return []

    missing = await missing_channels(
        channels, telegram_id=telegram_id, is_member=_membership(bot)
    )
    if not missing and cache is not None:
        await cache.set(key, "1", ttl_seconds=PASS_TTL_SECONDS)
    return missing


def _membership(bot: Any) -> Callable[[str, int], Awaitable[bool | None]]:
    async def check(chat_ref: str, telegram_id: int) -> bool | None:
        try:
            member = await bot.get_chat_member(chat_id=chat_ref, user_id=telegram_id)
        except Exception as exc:
            # Almost always "the bot is not an administrator of that channel".
            # Named here because the operator is the only one who can fix it,
            # and the customer must never be the one who finds out.
            logger.warning(
                "bot.channel_gate.uncheckable",
                chat_ref=chat_ref,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        return str(getattr(member, "status", "")) not in _ABSENT

    return check


def _is_recheck(event: TelegramObject) -> bool:
    return isinstance(event, CallbackQuery) and (event.data or "") == RECHECK


def gate_keyboard(missing: list[RequiredChannel]) -> Any:
    """A join button per channel, then the one that re-runs the check."""
    rows = [
        [InlineKeyboardButton(text=f"📢 {channel.title_fa}", url=channel.url)]
        for channel in missing
        if channel.url is not None
    ]
    rows.append([K.btn(T.GATE_RECHECK, RECHECK, style=K.YES)])
    return K.stack(rows)


def gate_text(missing: list[RequiredChannel]) -> str:
    named = "\n".join(f"• {channel.title_fa}" for channel in missing)
    return T.GATE_BODY.format(channels=named)


async def _show_gate(event: TelegramObject, missing: list[RequiredChannel]) -> None:
    body = gate_text(missing)
    markup = gate_keyboard(missing)
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message is not None:
            await event.message.answer(body, reply_markup=markup)
        return
    if isinstance(event, Message):
        await event.answer(body, reply_markup=markup)


__all__ = [
    "PASS_TTL_SECONDS",
    "RECHECK",
    "ChannelGateMiddleware",
    "gate_keyboard",
    "gate_text",
    "unjoined",
]
