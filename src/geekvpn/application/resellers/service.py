"""Reseller administration and the credit that makes a sale possible.

Two audiences, one service. An operator creates a reseller, sets their
discount, tops up their credit and picks their panels; the reseller spends
that credit. Both go through here, so a balance can only move in one place and
every movement writes a ledger row on the way past.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from geekvpn.application.identity.manage_admins import ManageAdmins
from geekvpn.application.resellers.ports import (
    Clock,
    LedgerEntry,
    PlanPrices,
    ResellerRepository,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.domain.resellers.errors import ResellerNotFound
from geekvpn.domain.resellers.reseller import PriceOverride, Reseller

#: Ledger kinds. Short strings rather than an enum in the database, matching
#: how the wallet ledger already spells its own.
TOPUP = "topup"
SALE = "sale"
REFUND = "refund"
ADJUSTMENT = "adjustment"


@dataclass(frozen=True, slots=True)
class NewReseller:
    """A reseller and the login that was created with them.

    The password is returned exactly once, here, and never stored in readable
    form. An operator who loses it resets it; there is no way to read it back,
    which is the point.
    """

    reseller: Reseller
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class QuotedPlan:
    plan_id: uuid.UUID
    list_price: Money
    reseller_price: Money

    @property
    def saving(self) -> Money:
        return Money(max(0, self.list_price.amount - self.reseller_price.amount))


class ResellerService:
    def __init__(
        self,
        *,
        resellers: ResellerRepository,
        admins: ManageAdmins,
        prices: PlanPrices,
        clock: Clock,
    ) -> None:
        self._resellers = resellers
        self._admins = admins
        self._prices = prices
        self._clock = clock

    # -- administration ----------------------------------------------------

    async def create(
        self,
        *,
        username: str,
        name_fa: str,
        discount_percent: int = 0,
        contact_fa: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> NewReseller:
        """A login and a reseller record, together.

        Together on purpose. Either alone is a broken state: an account with
        the role and no record signs in and can do nothing, and a record with
        no account is a price list nobody can reach.
        """
        # Generated, not chosen, and shown once. Nobody types a password into
        # a chat or an operator's browser to create somebody else's account.
        password = secrets.token_urlsafe(24)
        profile = await self._admins.create(
            username=username,
            password=password,
            role=AdminRole.RESELLER,
            actor_id=actor_id,
        )

        reseller = Reseller(
            id=uuid.uuid4(),
            admin_id=profile.id,
            name_fa=name_fa.strip(),
            discount_percent=discount_percent,
            contact_fa=contact_fa,
        )
        await self._resellers.add(reseller)
        return NewReseller(reseller=reseller, username=profile.username, password=password)

    async def get(self, reseller_id: uuid.UUID) -> Reseller:
        reseller = await self._resellers.get(reseller_id)
        if reseller is None:
            raise ResellerNotFound("No such reseller.")
        return reseller

    async def for_admin(self, admin_id: uuid.UUID) -> Reseller:
        """Whose rows the caller may see. The whole of reseller scoping."""
        reseller = await self._resellers.get_by_admin(admin_id)
        if reseller is None:
            raise ResellerNotFound("This account is not a reseller.")
        return reseller

    async def list_all(self) -> Sequence[Reseller]:
        return await self._resellers.list_all()

    async def update(
        self,
        reseller_id: uuid.UUID,
        *,
        name_fa: str | None = None,
        status: ResellerStatus | None = None,
        discount_percent: int | None = None,
        contact_fa: str | None = None,
    ) -> Reseller:
        reseller = await self.get(reseller_id)
        if name_fa is not None:
            reseller.name_fa = name_fa.strip()
        if contact_fa is not None:
            reseller.contact_fa = contact_fa.strip() or None
        if status is not None:
            reseller.status = status
        if discount_percent is not None:
            # Through the aggregate, so the cap is enforced in one place rather
            # than by whichever caller remembered.
            reseller.set_discount(discount_percent)
        await self._resellers.save(reseller)
        return reseller

    async def set_panels(self, reseller_id: uuid.UUID, node_ids: Sequence[str]) -> Reseller:
        """Which panels this reseller may provision on.

        An empty list means every panel, which is what an operator who has not
        made a decision yet has said. Refusing to provision at all would be a
        strange reading of "unset".
        """
        reseller = await self.get(reseller_id)
        reseller.allowed_node_ids = frozenset(node_ids)
        await self._resellers.save(reseller)
        return reseller

    async def set_overrides(
        self, reseller_id: uuid.UUID, overrides: dict[uuid.UUID, int]
    ) -> Reseller:
        reseller = await self.get(reseller_id)
        reseller.overrides = tuple(
            PriceOverride(plan_id=plan_id, price=Money(price))
            for plan_id, price in overrides.items()
        )
        await self._resellers.save(reseller)
        return reseller

    # -- credit ------------------------------------------------------------

    async def adjust_credit(
        self,
        reseller_id: uuid.UUID,
        *,
        amount: int,
        description_fa: str,
        actor_id: int | None = None,
        kind: str = ADJUSTMENT,
    ) -> Reseller:
        """Move a balance by hand, up or down.

        Signed, and it goes through the aggregate in both directions, so a
        deduction that would take a reseller below zero raises here rather than
        writing a negative balance the check constraint would reject later with
        a message nobody can read.
        """
        reseller = await self.get(reseller_id)
        if amount >= 0:
            reseller.credit(Money(amount))
        else:
            # `charge` refuses on a suspended account, which is right for a
            # sale and wrong for an operator correcting a mistake. Suspended
            # resellers still have balances that need fixing.
            debit = Money(-amount)
            if debit.amount > reseller.balance.amount:
                from geekvpn.domain.resellers.errors import InsufficientCredit

                raise InsufficientCredit(
                    needed=debit.amount, available=reseller.balance.amount
                )
            reseller.balance = Money(reseller.balance.amount - debit.amount)

        await self._resellers.save(reseller)
        await self._resellers.record(
            reseller_id=reseller.id,
            entry_id=uuid.uuid4().hex,
            amount=amount,
            balance_after=reseller.balance.amount,
            kind=kind if amount < 0 else (TOPUP if kind == ADJUSTMENT else kind),
            description_fa=description_fa,
            occurred_at=self._clock.now(),
            actor_id=actor_id,
        )
        return reseller

    async def charge_for_sale(
        self,
        reseller_id: uuid.UUID,
        *,
        amount: Money,
        description_fa: str,
        reference: str | None = None,
    ) -> Reseller:
        """Draw a sale down. Raises before anything is provisioned."""
        reseller = await self.get(reseller_id)
        reseller.charge(amount)
        await self._resellers.save(reseller)
        await self._resellers.record(
            reseller_id=reseller.id,
            entry_id=uuid.uuid4().hex,
            amount=-amount.amount,
            balance_after=reseller.balance.amount,
            kind=SALE,
            description_fa=description_fa,
            occurred_at=self._clock.now(),
            reference=reference,
        )
        return reseller

    async def refund_sale(
        self,
        reseller_id: uuid.UUID,
        *,
        amount: Money,
        description_fa: str,
        reference: str | None = None,
    ) -> Reseller:
        """Give credit back when provisioning failed after the charge.

        The charge happens first so a reseller cannot spend a balance they do
        not have; that ordering means a panel that refuses the account leaves
        money debited for nothing, and this is the other half.
        """
        reseller = await self.get(reseller_id)
        reseller.credit(amount)
        await self._resellers.save(reseller)
        await self._resellers.record(
            reseller_id=reseller.id,
            entry_id=uuid.uuid4().hex,
            amount=amount.amount,
            balance_after=reseller.balance.amount,
            kind=REFUND,
            description_fa=description_fa,
            occurred_at=self._clock.now(),
            reference=reference,
        )
        return reseller

    async def history(
        self, reseller_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[LedgerEntry]:
        return await self._resellers.history(reseller_id, limit=limit)

    # -- pricing -----------------------------------------------------------

    async def quote(self, reseller_id: uuid.UUID, plan_id: uuid.UUID) -> QuotedPlan | None:
        """What one package costs this reseller, beside what it costs anyone."""
        reseller = await self.get(reseller_id)
        list_price = await self._prices.list_price(plan_id)
        if list_price is None:
            return None
        return QuotedPlan(
            plan_id=plan_id,
            list_price=list_price,
            reseller_price=reseller.price_for(plan_id, list_price),
        )


__all__ = [
    "ADJUSTMENT",
    "REFUND",
    "SALE",
    "TOPUP",
    "NewReseller",
    "QuotedPlan",
    "ResellerService",
]
