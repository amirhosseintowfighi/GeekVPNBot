"""Paying the referrer when the person they invited buys something.

The other half of a programme the bot has been advertising since it shipped.
`referral_accruals` computed both sides of it into every `PriceQuote`, and
nothing ever read the result - so the screen promised "۱۰٪ از اولین خرید
دوستت" and no wallet was ever credited.

Three rules do the work.

**Paid once, on the first purchase.** The edge carries `converted_at`, and the
ledger entry carries a reference derived from the order, so a re-delivered
`OrderPaid` writes the `(user_id, kind, reference)` the ledger already holds a
unique constraint on. The check below usually gets there first; the constraint
catches the race it cannot.

**The order decides, not the quote.** The reward is a percentage of what was
actually paid, read off the paid order - not off a quote computed at some
earlier moment against prices that may since have changed.

**A failure here never touches the purchase.** This runs as a subscriber to
`OrderPaid`, after the money has moved and the service is being built. A
referrer whose wallet cannot be credited is a bonus to pay by hand; an
exception thrown into the delivery path is a customer who paid and got
nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

import structlog

from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.application.ports.clock import Clock
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.rewards import ReferralPolicy
from geekvpn.domain.payments.enums import TransactionKind

logger = structlog.stdlib.get_logger(__name__)

#: What the referrer sees in their wallet history.
REASON_FA = "پاداش دعوت دوستان"

KIND = TransactionKind.REFERRAL_REWARD


@dataclass(frozen=True, slots=True)
class ReferralEdge:
    """One referrer-to-invitee link, as this service needs to see it."""

    referrer_telegram_id: int
    invitee_telegram_id: int
    converted_at: datetime | None

    @property
    def is_first_purchase(self) -> bool:
        return self.converted_at is None


@runtime_checkable
class ReferralLedger(Protocol):
    """The edge, read and settled synchronously beside the wallet."""

    def edge_for_invitee(self, invitee_telegram_id: int) -> ReferralEdge | None: ...

    def settle(
        self,
        *,
        invitee_telegram_id: int,
        order_id: str,
        paid: int,
        reward: int,
        at: datetime,
    ) -> None:
        """Record what this order did to the edge.

        Revenue is added on every order; `converted_at` and `first_order_id`
        are set only the first time, because "invited" and "converted" are two
        different numbers on the operator's report and adding them together
        would be a lie about how the programme performs.
        """
        ...


class ReferralRewards:
    def __init__(
        self,
        *,
        ledger: ReferralLedger,
        wallets: WalletService,
        policy: Callable[[], ReferralPolicy],
        clock: Clock,
    ) -> None:
        self._ledger = ledger
        self._wallets = wallets
        #: A callable, not a policy: settings change between one order and the
        #: next, and a value captured when the scope was built would pay
        #: yesterday's rate for as long as the process lived.
        self._policy = policy
        self._clock = clock

    def on_order_paid(self, event: object) -> None:
        """Handle ``OrderPaid``.

        Typed loosely for the same reason `OrderPaymentBridge` is: binding this
        to the provisioning module would point the dependency the wrong way.
        """
        order_id = getattr(event, "order_id", None)
        buyer = getattr(event, "user_id", None)
        total = getattr(event, "total", None)
        if not isinstance(order_id, str) or not isinstance(buyer, int):
            return
        if not isinstance(total, int) or total <= 0:
            return

        try:
            self._settle(order_id=order_id, buyer=buyer, total=total)
        except Exception:
            # See the module docstring: the purchase has already happened.
            logger.exception("referral.reward_failed", order_id=order_id, user_id=buyer)

    def _settle(self, *, order_id: str, buyer: int, total: int) -> None:
        edge = self._ledger.edge_for_invitee(buyer)
        if edge is None:
            return

        policy = self._policy()
        reward = policy.reward_for_order(
            paid=Money(total), is_first_purchase=edge.is_first_purchase
        )

        if reward:
            self._wallets.credit_reward(
                user_id=edge.referrer_telegram_id,
                amount=reward,
                kind=KIND,
                description_fa=REASON_FA,
                # Derived from the order, so a re-delivered event collides with
                # the row that is already there instead of paying twice.
                reference=f"referral:{order_id}",
            )

        self._ledger.settle(
            invitee_telegram_id=buyer,
            order_id=order_id,
            paid=total,
            reward=reward.amount,
            at=self._clock.now(),
        )


__all__ = ["KIND", "REASON_FA", "ReferralEdge", "ReferralLedger", "ReferralRewards"]
