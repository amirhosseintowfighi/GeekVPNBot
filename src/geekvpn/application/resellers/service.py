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
from geekvpn.application.resellers.arrears import ArrearsEnforcer
from geekvpn.application.resellers.ports import (
    BotTokens,
    Clock,
    LedgerEntry,
    PlanPrices,
    ResellerRepository,
)
from geekvpn.application.resellers.tenant_bots import tenant_path, tenant_secret
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


def _merged(
    existing: tuple[PriceOverride, ...],
    changes: dict[uuid.UUID, Money],
    *,
    field: str,
) -> tuple[PriceOverride, ...]:
    """Apply one half of a plan's pricing, leaving the other half alone.

    Cost is an operator's decision and retail is the reseller's, so a write to
    either must not erase the other. Sent whole within its own half: a plan
    missing from `changes` has that half cleared, which is how somebody removes
    an override rather than needing a second endpoint to do it.
    """
    by_plan = {override.plan_id: override for override in existing}
    plan_ids = set(by_plan) | set(changes)
    merged: list[PriceOverride] = []
    for plan_id in plan_ids:
        current = by_plan.get(plan_id)
        cost = current.cost if current else None
        retail = current.retail if current else None
        if field == "cost":
            cost = changes.get(plan_id)
        else:
            retail = changes.get(plan_id)
        if cost is None and retail is None:
            continue
        merged.append(PriceOverride(plan_id=plan_id, cost=cost, retail=retail))
    return tuple(sorted(merged, key=lambda o: str(o.plan_id)))


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
        arrears: ArrearsEnforcer | None = None,
        tokens: BotTokens | None = None,
    ) -> None:
        self._resellers = resellers
        self._admins = admins
        self._prices = prices
        self._clock = clock
        # Optional so the service is testable without a panel behind it. In
        # the container it is always present - a balance that can go under with
        # nothing watching is a credit limit that does not exist.
        self._arrears = arrears
        # Also optional, and for the same reason: a deployment without a
        # Telegram client can still create resellers and move their credit.
        self._token_port = tokens

    @property
    def _tokens(self) -> BotTokens:
        if self._token_port is None:
            raise RuntimeError("This deployment has no Telegram client configured.")
        return self._token_port

    async def _enforce(self, reseller: Reseller) -> None:
        """Bring this reseller's customers in line with their balance.

        After every movement, not only the ones that cross zero. Crossing is
        not something this can detect reliably: a previous run may have failed
        on a node that was down, and re-reading the truth each time is what
        makes that self-healing rather than permanent.
        """
        if self._arrears is None:
            return
        await self._arrears.apply(
            reseller_id=reseller.id, in_arrears=reseller.in_arrears
        )

    # -- administration ----------------------------------------------------

    async def create(
        self,
        *,
        username: str,
        name_fa: str,
        discount_percent: int = 0,
        contact_fa: str | None = None,
        telegram_id: int | None = None,
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
            # How they get into the bot. The bot authenticates an operator by
            # Telegram id, so an account without one can sign into the panel
            # and is a stranger to the bot - which is half a reseller.
            telegram_id=telegram_id,
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
        brand_fa: str | None = None,
    ) -> Reseller:
        reseller = await self.get(reseller_id)
        if brand_fa is not None:
            # Empty clears it, falling back to their own name rather than to
            # ours - a customer seeing the reseller's name is right either way.
            reseller.brand_fa = brand_fa.strip() or None
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

    async def set_costs(
        self, reseller_id: uuid.UUID, costs: dict[uuid.UUID, int]
    ) -> Reseller:
        """What the platform charges this reseller, package by package.

        An operator's decision. Sent whole, and it leaves the reseller's own
        retail prices alone - the two are set by two different people and
        neither should be able to erase the other by omission.
        """
        reseller = await self.get(reseller_id)
        reseller.overrides = _merged(
            reseller.overrides,
            {plan_id: Money(price) for plan_id, price in costs.items()},
            field="cost",
        )
        await self._resellers.save(reseller)
        return reseller

    async def set_retail(
        self, reseller_id: uuid.UUID, prices: dict[uuid.UUID, int]
    ) -> Reseller:
        """What this reseller charges their own customers.

        Theirs, not ours. Any number they like, including below what it costs
        them - a reseller running a loss-leader is doing business, and this
        platform is not their accountant.
        """
        reseller = await self.get(reseller_id)
        reseller.overrides = _merged(
            reseller.overrides,
            {plan_id: Money(price) for plan_id, price in prices.items()},
            field="retail",
        )
        await self._resellers.save(reseller)
        return reseller

    # -- their own bot -----------------------------------------------------

    async def attach_bot(
        self,
        reseller_id: uuid.UUID,
        *,
        token: str,
        webhook_base_url: str,
        webhook_path: str,
        platform_secret: str,
    ) -> str:
        """Store a reseller's bot token and point Telegram at us.

        Both halves, in that order, and the order is the point. Storing without
        registering leaves a reseller with a bot that answers nothing;
        registering without storing leaves Telegram delivering updates for a
        token this platform cannot identify.

        The token is verified against Telegram before either. A token that has
        never been checked is a bot that will silently receive nothing,
        discovered by a reseller whose customers are already waiting.

        Returns the bot's @username - the only part of this an operator sees.
        """
        reseller = await self.get(reseller_id)
        identity = await self._tokens.identify(token)

        await self._resellers.set_bot(
            reseller.id, token=token.strip(), username=identity.username
        )
        await self._tokens.register_webhook(
            token=token.strip(),
            url=webhook_base_url.rstrip("/") + tenant_path(webhook_path, reseller.id),
            secret=tenant_secret(platform_secret, reseller.id),
        )
        return identity.username

    async def detach_bot(self, reseller_id: uuid.UUID) -> None:
        """Forget the token and stop Telegram sending to us.

        Telegram is told first: a token cleared while Telegram still holds the
        webhook leaves updates arriving for a tenant that no longer exists,
        which is a retry loop rather than a clean stop.
        """
        reseller = await self.get(reseller_id)
        token = await self._resellers.bot_token(reseller.id)
        if token:
            await self._tokens.clear_webhook(token=token)
        await self._resellers.set_bot(reseller.id, token=None, username=None)

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
        # `settle` rather than `charge`: an operator correcting a balance is
        # not making a sale, and this is the one path allowed to go below zero.
        # A reseller in arrears has their customers suspended until it is
        # positive again, which is the credit limit this platform enforces.
        reseller.settle(amount)

        await self._resellers.save(reseller)
        await self._resellers.record(
            reseller_id=reseller.id,
            entry_id=uuid.uuid4().hex,
            amount=amount,
            balance_after=reseller.balance_amount,
            kind=kind if amount < 0 else (TOPUP if kind == ADJUSTMENT else kind),
            description_fa=description_fa,
            occurred_at=self._clock.now(),
            actor_id=actor_id,
        )
        await self._enforce(reseller)
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
            balance_after=reseller.balance_amount,
            kind=SALE,
            description_fa=description_fa,
            occurred_at=self._clock.now(),
            reference=reference,
        )
        await self._enforce(reseller)
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
            balance_after=reseller.balance_amount,
            kind=REFUND,
            description_fa=description_fa,
            occurred_at=self._clock.now(),
            reference=reference,
        )
        await self._enforce(reseller)
        return reseller

    async def history(
        self, reseller_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[LedgerEntry]:
        return await self._resellers.history(reseller_id, limit=limit)

    async def summary(self, reseller_id: uuid.UUID) -> dict[str, int]:
        """The few numbers a reseller needs about their own trade.

        Read off their own ledger rather than the platform's analytics, which
        is scoped to nothing and would be a second door into everyone's figures
        for a screen that only needs four sums.
        """
        entries = list(await self._resellers.history(reseller_id, limit=500))
        sales = [entry for entry in entries if entry.kind == SALE]
        topups = [entry for entry in entries if entry.kind in (TOPUP, ADJUSTMENT)]
        spent = sum(-entry.amount for entry in sales)
        return {
            "sales": len(sales),
            "spent": spent,
            "topped_up": sum(entry.amount for entry in topups if entry.amount > 0),
            # What they have made, if they charge what they say they charge.
            # Their own retail prices are the only figure we have for it.
            "average_sale": spent // len(sales) if sales else 0,
        }

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
