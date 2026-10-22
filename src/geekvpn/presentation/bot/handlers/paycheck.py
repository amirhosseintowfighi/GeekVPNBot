""" "Check my payment": ask the gateway now, instead of waiting for the sweep.

The worker asks about every payment waiting at a gateway every half minute,
so this button is never the only way a payment settles - it is for the
customer who has just paid and is looking at the chat. It asks in the
payment's own shop, so a reseller's customer is checked with the reseller's
merchant account.

Only the payment's owner may ask, and not more than once every few seconds:
each tap is a request to the gateway.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery

from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.payments.gateway_verification import owner_of, verify_payment
from geekvpn.presentation.bot.handlers.common import toast
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import PayCB

logger = get_logger("bot.paycheck")

router = Router(name="paycheck")

COOLDOWN_SECONDS = 10

_ANSWER = {
    str(VerificationOutcome.CONFIRMED): T.PAYCHECK_CONFIRMED,
    str(VerificationOutcome.DECLINED): T.PAYCHECK_DECLINED,
    str(VerificationOutcome.MISMATCH): T.PAYCHECK_REVIEW,
}


@router.callback_query(PayCB.filter(F.action == "check"))
async def on_check(
    query: CallbackQuery, callback_data: PayCB, container: Container, user: Any = None
) -> None:
    payment_id = callback_data.ref
    if user is None or not payment_id:
        await toast(query, T.ERR_GENERIC, alert=True)
        return
    key = f"paycheck:{user.telegram_id}:{payment_id}"
    if not await container.cache.add_if_absent(key, "1", ttl_seconds=COOLDOWN_SECONDS):
        await toast(query, T.PAYCHECK_WAIT, alert=True)
        return

    owner = await asyncio.to_thread(owner_of, container, payment_id)
    if owner != user.telegram_id:
        # Somebody else's payment, or none: the same answer, so ids cannot be probed.
        await toast(query, T.PAYCHECK_NOT_FOUND, alert=True)
        return
    try:
        result = await asyncio.to_thread(verify_payment, container, payment_id)
        outcome = str(result.outcome)
    except Exception:
        logger.exception("bot.paycheck_failed", payment_id=payment_id)
        outcome = ""
    await toast(query, _ANSWER.get(outcome, T.PAYCHECK_PENDING), alert=True)


__all__ = ["router"]
