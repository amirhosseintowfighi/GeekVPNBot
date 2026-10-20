"""Asking a gateway about a payment, in the shop the payment belongs to.

Two things went wrong here before, and both left paid customers with nothing:

**Nothing asked.** `VerificationService.sweep` was written to re-check every
payment waiting at a gateway, and nothing ever called it. A redirect gateway
got away with that - the customer comes back to `/pay/callback` and that
verifies - but AtlasPay's customer pays inside AtlasPay's own mini app and
never comes back, so an approved AtlasPay payment was never noticed by us at
all. The same was true of every provider confirmed by asking: NowPayments,
TON, Stars when the bot missed the update.

**The wrong shop asked.** The callback verified in the platform's scope, whose
registry holds the platform's merchant accounts. A reseller's payment was
looked up with our AtlasPay key, or found no gateway at all.

So the shop is read off the payment row first, and the scope - registry,
repositories, notifications - is built for that shop.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from geekvpn.domain.payments.enums import PaymentState
from geekvpn.domain.payments.gateway import VerificationResult
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.sync_scope import build_sync_scope
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.persistence.models.payments import PaymentModel

logger = get_logger(__name__)

#: How far back the sweep looks. AtlasPay's window is twenty minutes and a
#: disputed shortfall a few hours; a payment still "at the gateway" after two
#: days is stuck for a reason no amount of asking will fix, and asking about
#: it every half minute forever is a request per tick for nothing.
SWEEP_WINDOW = timedelta(days=2)
SWEEP_LIMIT = 200


def verify_payment(container: Container, payment_id: str) -> VerificationResult:
    """Verify one payment in its own shop, and commit what that settled.

    Its own transaction: one payment's panel failing must not roll back
    another customer's confirmation.
    """
    with container.sync_sessions() as session:
        row = session.get(PaymentModel, payment_id)
        shop = row.reseller_id if row is not None else None
        scope = build_sync_scope(container, session, reseller_id=shop)
        try:
            result = scope.verification.verify(payment_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return result


def owner_of(container: Container, payment_id: str) -> int | None:
    """Whose payment this is, for a customer asking about their own."""
    with container.sync_sessions() as session:
        row = session.get(PaymentModel, payment_id)
        return int(row.user_id) if row is not None else None


def waiting_at_a_gateway(container: Container) -> list[str]:
    """Every shop's payments still waiting on a provider, oldest first."""
    since = container.clock.now() - SWEEP_WINDOW
    with container.sync_sessions() as session:
        rows = session.execute(
            select(PaymentModel.id)
            .where(
                PaymentModel.state == PaymentState.PENDING_GATEWAY.value,
                PaymentModel.created_at >= since,
            )
            .order_by(PaymentModel.created_at)
            .limit(SWEEP_LIMIT)
        ).scalars()
        return list(rows)


def sweep_gateways(container: Container) -> dict[str, int]:
    """Ask about each waiting payment once. Never raises; counts outcomes."""
    counts: dict[str, int] = {}
    for payment_id in waiting_at_a_gateway(container):
        try:
            outcome = str(verify_payment(container, payment_id).outcome)
        except Exception:
            logger.exception("gateway.verify_failed", payment_id=payment_id)
            outcome = "error"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


__all__ = [
    "SWEEP_WINDOW",
    "owner_of",
    "sweep_gateways",
    "verify_payment",
    "waiting_at_a_gateway",
]
