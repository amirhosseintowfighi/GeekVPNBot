"""Helpers shared by every handler.

The important one is `safe_edit`. Telegram raises `TelegramBadRequest` with
"message is not modified" when an edit produces byte-identical content, which
happens constantly with refresh buttons and idempotent navigation. That is not
an error condition -- it means the screen is already correct -- so it is
swallowed here rather than in forty call sites.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.domain.catalog.rewards import (
    TIER_CASHBACK_BONUS_BPS,
    TIER_LABEL_FA,
    TIER_THRESHOLDS,
    LoyaltyTier,
)
from geekvpn.presentation.bot.ui import emoji as E

# Telegram hard-caps a message body at 4096 characters. Renderers stay well
# under it, but a user-supplied string (a long ticket subject) could push a
# body over, so every send goes through the clamp.
TELEGRAM_MAX = 4096


def clamp(body: str) -> str:
    if len(body) <= TELEGRAM_MAX:
        return body
    return body[: TELEGRAM_MAX - 1] + "\u2026"


async def safe_edit(
    query: CallbackQuery,
    body: str,
    *,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the message behind a callback query, tolerating a no-op edit."""
    message = query.message
    if not isinstance(message, Message):
        # Either the original aged out of the client's cache (48h+) or Telegram
        # sent an InaccessibleMessage stub. Neither can be edited; the caller
        # should have already answered the query.
        return
    try:
        await message.edit_text(clamp(body), reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def answer(message: Message, body: str, **kwargs: Any) -> Message:
    return await message.answer(clamp(body), **kwargs)


async def toast(query: CallbackQuery, text: str = "", *, alert: bool = False) -> None:
    """Acknowledge a callback query.

    Always call this. An unanswered callback leaves a spinner on the user's
    button for ~30 seconds, which reads as a frozen bot.
    """
    try:
        await query.answer(text or None, show_alert=alert)
    except TelegramBadRequest:
        # Query older than 60s -- Telegram refuses. Harmless.
        return


def short_ref(value: uuid.UUID | str) -> str:
    """An 8-character handle for a UUID.

    Callback data is capped at 64 bytes and a full UUID is 36 characters, so
    two of them plus a prefix will not fit. We pass this token and resolve it
    against a list we already hold.
    """
    return str(value).replace("-", "")[:8]


def match_ref(items: list[Any], ref: str, attribute: str) -> Any | None:
    """Resolve a short ref back to its object.

    Returns `None` on a miss, which handlers surface as `ERR_STALE_BUTTON` --
    the honest explanation, since a miss means the underlying list changed
    since the keyboard was rendered.
    """
    for item in items:
        if short_ref(getattr(item, attribute)) == ref:
            return item
    return None


def tier_of(lifetime_spend: int) -> LoyaltyTier:
    """Highest tier whose threshold the customer has passed."""
    reached = LoyaltyTier.BRONZE
    for tier, threshold in TIER_THRESHOLDS.items():
        if lifetime_spend >= threshold:
            reached = tier
    return reached


def tier_label(tier: LoyaltyTier) -> str:
    return TIER_LABEL_FA.get(tier, TIER_LABEL_FA[LoyaltyTier.BRONZE])


def tier_emoji(tier: LoyaltyTier) -> str:
    return E.TIER_EMOJI.get(tier.value, E.TIER_EMOJI["bronze"])


def next_tier(tier: LoyaltyTier) -> tuple[LoyaltyTier | None, int | None]:
    """The tier above `tier`, and the spend needed to reach it."""
    ordered = sorted(TIER_THRESHOLDS.items(), key=lambda kv: kv[1])
    for index, (candidate, _) in enumerate(ordered):
        if candidate is tier and index + 1 < len(ordered):
            following, threshold = ordered[index + 1]
            return following, threshold
    return None, None


def cashback_bps_for(tier: LoyaltyTier, *, base_bps: int) -> int:
    return base_bps + TIER_CASHBACK_BONUS_BPS.get(tier, 0)


def display_name_of(user: Any) -> str:
    """Best available name, never empty.

    Falls back through display name -> Telegram first name -> a generic
    Persian noun, because `سلام None` is the kind of thing that ends up in a
    screenshot on Twitter.
    """
    for attribute in ("display_name", "first_name", "username"):
        value = getattr(user, attribute, None)
        if value:
            return str(value)
    return "\u062f\u0648\u0633\u062a \u0639\u0632\u06cc\u0632"


def local_hour(now: datetime, *, offset_hours: float = 3.5) -> int:
    """Hour of day in Iran time.

    Iran is UTC+03:30 and has not observed DST since 2022, so a fixed offset
    is correct and avoids a tzdata dependency in the hot path.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    shifted = now.timestamp() + offset_hours * 3600
    return int((shifted // 3600) % 24)
