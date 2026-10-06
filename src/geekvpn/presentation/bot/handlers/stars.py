"""Telegram Stars: the two updates a paid invoice produces.

`pre_checkout_query` must be answered within ten seconds or Telegram cancels
the payment, so it says yes to anything that is not plainly closed. The
amount is not checked here: verification reads what was actually paid from
the bot's own transaction list, and refusing on a guess here would only lose
a sale.

`successful_payment` then asks for that verification at once, so the service
is delivered while the customer is still looking at the chat. If this update
is lost - the bot was restarting - the payment sweeper finds it anyway.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from geekvpn.domain.payments.enums import PaymentState, VerificationOutcome
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import answer
from geekvpn.presentation.bot.ui import text as T

logger = get_logger("bot.stars")

router = Router(name="stars")

#: A payment in one of these has been decided; paying it again is a mistake.
_CLOSED = frozenset(
    {
        PaymentState.APPROVED,
        PaymentState.REJECTED,
        PaymentState.EXPIRED,
        PaymentState.FAILED,
        PaymentState.REFUNDED,
    }
)


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, scope: Any = None, **_: Any) -> None:
    payload = query.invoice_payload

    def state_of(sync: Any) -> Any:
        payment = sync.payments.get(payload)
        return None if payment is None else payment.state

    try:
        state = await scope.in_shop(state_of) if scope is not None else None
    except Exception:
        # Unknown is not closed. Saying no would cancel a payment that may be
        # perfectly fine, and verification decides it either way.
        logger.warning("stars.precheckout_lookup_failed", payload=payload, exc_info=True)
        state = None
    if state in _CLOSED:
        await query.answer(ok=False, error_message=T.STARS_PAYMENT_CLOSED)
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, scope: Any = None, **_: Any) -> None:
    paid = message.successful_payment
    if paid is None or paid.currency != "XTR":
        return
    payload = paid.invoice_payload

    def verify(sync: Any) -> str:
        return str(sync.verification.verify(payload).outcome)

    try:
        outcome = await scope.in_shop(verify) if scope is not None else ""
    except Exception:
        logger.exception("stars.verify_failed", payload=payload)
        outcome = ""
    if outcome == str(VerificationOutcome.CONFIRMED):
        # The delivery message follows from the payment's own events.
        await answer(message, T.STARS_PAID)
    else:
        await answer(message, T.STARS_CHECKING)


__all__ = ["router"]
