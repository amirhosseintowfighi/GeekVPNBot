"""A word to a customer who leaves one of the shop's required channels.

Only when the operator wrote one (channels.leave_message_fa), and only for a
required channel - the bot sees membership changes in every chat it
administers, and a goodbye for leaving an unrelated group would be strange.
The join button comes with it, so coming back is one tap.

Telegram delivers these only to a bot that is an administrator of the
channel, and only because a `chat_member` handler is registered: the
dispatcher derives `allowed_updates` from the handlers it has.
"""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from geekvpn.application.platform.settings_service import CHANNEL_LEAVE_MESSAGE_FA
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.channel_gate import gate_keyboard

logger = get_logger("bot.channel_leave")

router = Router(name="channel_leave")

_INSIDE = {"member", "administrator", "creator", "restricted"}
_OUTSIDE = {"left", "kicked"}


def _matches(chat_ref: str, update: ChatMemberUpdated) -> bool:
    if chat_ref.lstrip("-").isdigit():
        return int(chat_ref) == update.chat.id
    username = (update.chat.username or "").lower()
    return bool(username) and chat_ref.lstrip("@").lower() == username


@router.chat_member()
async def on_member_change(update: ChatMemberUpdated, bot: Any, scope: Any = None) -> None:
    if scope is None:
        return
    if (
        update.old_chat_member.status not in _INSIDE
        or update.new_chat_member.status not in _OUTSIDE
    ):
        return
    message = await scope.settings_service.get(CHANNEL_LEAVE_MESSAGE_FA)
    if not message:
        return
    channel = next(
        (c for c in await scope.required_channels.active() if _matches(c.chat_ref, update)),
        None,
    )
    if channel is None:
        return
    try:
        await bot.send_message(
            update.new_chat_member.user.id, message, reply_markup=gate_keyboard([channel])
        )
    except Exception:
        # They may have blocked the bot on the way out; nothing to do about it.
        logger.info("channel_leave.not_delivered", user=update.new_chat_member.user.id)
