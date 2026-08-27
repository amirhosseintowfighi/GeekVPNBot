"""The reseller aggregate: prices, credit, and which panels are theirs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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
    """What one package costs a reseller, and what they sell it for.

    Two different decisions by two different people, so two fields:

    ``cost`` is what the platform charges this reseller, set by an operator.
    ``None`` means the reseller's percentage applies - which is the usual
    case, because a percentage is the right shape for most of a catalogue and
    the wrong shape only at the edges: a trial that must not be discounted,
    a long plan at a negotiated flat rate.

    ``retail`` is what the reseller charges their own customer, set by the
    reseller. ``None`` means they have not decided and the platform's list
    price stands. It is theirs to set to anything, including below cost - a
    reseller running a loss-leader is doing business, not making a mistake,
    and this platform is not their accountant.
    """

    plan_id: uuid.UUID
    cost: Money | None = None
    retail: Money | None = None


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
    #: Signed Toman, and deliberately not `Money`.
    #:
    #: `Money` forbids negative amounts, which is right for a price and wrong
    #: for a ledger position. A reseller's balance can go under zero through an
    #: operator settlement, and the consequence is that their customers'
    #: services are suspended until it is positive again - that suspension is
    #: the credit limit this platform enforces, in place of a number nobody
    #: would keep up to date.
    balance_amount: int = 0
    #: Empty means every node. An operator who has not restricted anything has
    #: not yet made a decision, and refusing to provision at all would be a
    #: strange reading of that.
    allowed_node_ids: frozenset[str] = frozenset()
    overrides: tuple[PriceOverride, ...] = ()
    #: Whatever an operator needs to reach this person outside the platform.
    #: Free text: a phone number, a Telegram handle, a name and a note.
    contact_fa: str | None = None
    #: What their bot calls itself, when they have chosen. `None` means the
    #: platform's own name - which is a reasonable default and, more to the
    #: point, a name rather than a blank in their customer's first message.
    brand_fa: str | None = None

    def __post_init__(self) -> None:
        self.set_discount(self.discount_percent)

    def set_discount(self, percent: int) -> None:
        """The one place the cap is enforced, so callers cannot each forget."""
        if not 0 <= percent <= MAX_DISCOUNT_PERCENT:
            raise ValueError(f"discount must be between 0 and {MAX_DISCOUNT_PERCENT}")
        self.discount_percent = percent

    # -- pricing -----------------------------------------------------------

    def _override(self, plan_id: uuid.UUID) -> PriceOverride | None:
        for override in self.overrides:
            if override.plan_id == plan_id:
                return override
        return None

    def price_for(self, plan_id: uuid.UUID, list_price: Money) -> Money:
        """What this package costs this reseller.

        A cost override wins outright, including one higher than the list
        price: that is a negotiated rate, not an error to correct.
        """
        override = self._override(plan_id)
        if override is not None and override.cost is not None:
            return override.cost

        # Integer arithmetic, rounded down, in Toman. Rounding down means the
        # reseller is never charged a Toman more than the percentage promised,
        # and the platform's share absorbs the remainder.
        discounted = list_price.amount * (100 - self.discount_percent) // 100
        return Money(discounted)

    def retail_price_for(self, plan_id: uuid.UUID, list_price: Money) -> Money:
        """What this reseller charges their own customer.

        Theirs to decide. Until they do, the platform's list price stands -
        which is a reasonable default and, more importantly, is a number rather
        than a blank on the screen where their customer is choosing.
        """
        override = self._override(plan_id)
        if override is not None and override.retail is not None:
            return override.retail
        return list_price

    @property
    def retail_overrides(self) -> dict[uuid.UUID, Money]:
        """The prices this reseller has actually decided, for the storefront.

        Only what they set. A package they have left alone is absent rather
        than present at the list price, so the storefront falls back on its own
        and a later change to our list price still reaches their shop.
        """
        return {
            override.plan_id: override.retail
            for override in self.overrides
            if override.retail is not None
        }

    # -- credit ------------------------------------------------------------

    def charge(self, amount: Money) -> None:
        """Draw a *new sale* down against the balance.

        Refuses rather than going under. A reseller who cannot pay for a
        package should not be handed one - that is a different situation from
        an existing balance that has gone negative, which is handled by
        `in_arrears` below.
        """
        if not self.status.may_provision:
            raise ResellerSuspended("This reseller account cannot provision.")
        if amount.amount > self.balance_amount:
            raise InsufficientCredit(needed=amount.amount, available=self.balance_amount)
        self.balance_amount -= amount.amount

    @property
    def balance(self) -> Money:
        """The balance as `Money`, for the common case of showing a positive
        one. Clamped at zero: a negative balance is a signed number and callers
        that need it must say so by reading `balance_amount`."""
        return Money(max(0, self.balance_amount))

    def credit(self, amount: Money) -> None:
        """A top-up, or a refund of a sale that failed to provision."""
        self.balance_amount += amount.amount

    def settle(self, amount: int) -> None:
        """Move the balance by a signed amount, including below zero.

        The one path that may go negative, and only an operator reaches it: a
        correction, a disputed charge, an agreed settlement. What happens next
        is not a refusal but a consequence - a reseller in arrears has their
        customers' services suspended until the balance is positive again,
        which is the credit limit this platform actually enforces.
        """
        self.balance_amount += amount

    @property
    def in_arrears(self) -> bool:
        return self.balance_amount < 0

    # -- panels ------------------------------------------------------------

    def may_use(self, node_id: str) -> bool:
        return not self.allowed_node_ids or node_id in self.allowed_node_ids

    def require_node(self, node_id: str) -> None:
        if not self.may_use(node_id):
            raise NodeNotAllowed(node_id)


__all__ = ["MAX_DISCOUNT_PERCENT", "PriceOverride", "Reseller"]
