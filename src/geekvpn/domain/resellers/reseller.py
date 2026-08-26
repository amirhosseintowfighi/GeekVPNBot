"""The reseller aggregate: prices, credit, and which panels are theirs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.domain.resellers.errors import (
    InsufficientCredit,
    NodeNotAllowed,
    ResellerSuspended,
)

#: The most a reseller's discount may be. Not a hundred: a plan that costs a
#: reseller nothing is a mistake somebody made in a form, and it would drain
#: panel capacity for free until anyone noticed.
MAX_DISCOUNT_PERCENT = 90


@dataclass(frozen=True, slots=True)
class PriceOverride:
    """One package priced by hand for one reseller.

    A percentage is the right shape for most of a catalogue and the wrong shape
    for the edges: a loss-leader trial that must not be discounted at all, or a
    long plan sold at a negotiated flat rate. Overrides are those edges, so
    there are few of them and each one is deliberate.
    """

    plan_id: uuid.UUID
    price: Money


@dataclass(eq=False)
class Reseller:
    """Someone selling this platform under their own name.

    ``admin_id`` is their login: a reseller signs in through the same door as
    any operator, with a role that resolves to a small permission set. There is
    no second authentication system, and there must not be - a second way to
    prove who you are is a second way to get it wrong.
    """

    id: uuid.UUID
    admin_id: uuid.UUID
    name_fa: str
    status: ResellerStatus = ResellerStatus.ACTIVE
    discount_percent: int = 0
    balance: Money = field(default_factory=lambda: Money(0))
    #: Empty means every node. An operator who has not restricted anything has
    #: not yet made a decision, and refusing to provision at all would be a
    #: strange reading of that.
    allowed_node_ids: frozenset[str] = frozenset()
    overrides: tuple[PriceOverride, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.discount_percent <= MAX_DISCOUNT_PERCENT:
            raise ValueError(f"discount must be between 0 and {MAX_DISCOUNT_PERCENT}")

    # -- pricing -----------------------------------------------------------

    def price_for(self, plan_id: uuid.UUID, list_price: Money) -> Money:
        """What this package costs this reseller.

        An override wins outright, including an override that is higher than
        the list price: that is a negotiated rate, not an error to correct.
        """
        for override in self.overrides:
            if override.plan_id == plan_id:
                return override.price

        # Integer arithmetic, rounded down, in Toman. Rounding down means the
        # reseller is never charged a Toman more than the percentage promised,
        # and the platform's share absorbs the remainder.
        discounted = list_price.amount * (100 - self.discount_percent) // 100
        return Money(discounted)

    # -- credit ------------------------------------------------------------

    def charge(self, amount: Money) -> None:
        """Draw a sale down against the balance.

        Raises rather than going negative. Debt is a policy decision with a
        limit and a settlement process behind it, and pretending a balance can
        be negative is how a platform discovers it has extended a hundred
        million Toman of credit by accident.
        """
        if not self.status.may_provision:
            raise ResellerSuspended("This reseller account cannot provision.")
        if amount.amount > self.balance.amount:
            raise InsufficientCredit(needed=amount.amount, available=self.balance.amount)
        self.balance = Money(self.balance.amount - amount.amount)

    def credit(self, amount: Money) -> None:
        """A top-up, or a refund of a sale that failed to provision."""
        self.balance = Money(self.balance.amount + amount.amount)

    # -- panels ------------------------------------------------------------

    def may_use(self, node_id: str) -> bool:
        return not self.allowed_node_ids or node_id in self.allowed_node_ids

    def require_node(self, node_id: str) -> None:
        if not self.may_use(node_id):
            raise NodeNotAllowed(node_id)


__all__ = ["MAX_DISCOUNT_PERCENT", "PriceOverride", "Reseller"]
