"""System handlers only.

This exists to prove the wiring end to end (Telegram -> Nginx -> bot service ->
dispatcher -> identity middleware -> handler). All user-facing Persian flows
land in Phase 3.
"""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="system")


@router.message(Command("ping"))
async def ping(message: Message) -> None:
    """Connectivity check. Intentionally not localised - it is a diagnostic."""
    await message.answer("pong")


@router.message(Command("whoami"))
async def whoami(message: Message, user: Any = None) -> None:
    """Proves the identity middleware resolved (or created) an account.

    Diagnostic only, and deliberately not localised. Phase 3 replaces this
    with the real Persian onboarding flow.
    """
    if user is None:
        await message.answer("No account is associated with this chat.")
        return
    await message.answer(
        f"id: {user.id}\\ntelegram_id: {user.telegram_id}\\n"
        f"referral_code: {user.referral_code}\\nstatus: {user.status}"
    )
