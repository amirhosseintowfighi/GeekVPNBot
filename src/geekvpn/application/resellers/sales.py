"""A reseller selling one package to one of their own customers.

The whole flow is four steps in a fixed order, and the order is the design:

1. price it, from the reseller's own cost list;
2. take the credit, which refuses if they cannot pay;
3. place an order and provision it;
4. give the credit back if step three failed.

Charging *before* provisioning rather than after is deliberate. The other way
round, two sales racing each other both see enough balance and both provision,
and the platform has given away a package. This way the worst case is a debit
briefly held against a sale that did not happen - which step four undoes, and
which the ledger shows both halves of either way.

The reseller's customer is not a user of this platform. They exist in the
reseller's own bot and nowhere here, so the subscription is recorded against
the reseller's own account id: there is no Telegram user to attribute it to,
and inventing one would put strangers in the platform's customer list.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from geekvpn.application.resellers.service import ResellerService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderSource
from geekvpn.domain.resellers.errors import NodeNotAllowed, ResellerSuspended
from geekvpn.domain.resellers.reseller import Reseller

logger = structlog.stdlib.get_logger(__name__)


class PlanTerms(Protocol):
    """What a package promises, as the sale needs it.

    `base_price` is `Money`, matching the catalogue - the reseller's cost is
    derived from it and both go onto the order, so converting to and from a
    bare integer here would be two chances to lose a Toman.
    """

    id: uuid.UUID
    name_fa: str
    duration_days: int
    device_limit: int
    base_price: Money


class PlanCatalogue(Protocol):
    async def get(self, plan_id: uuid.UUID) -> Any | None: ...


class Orders(Protocol):
    """The slice of `OrderService` a reseller sale uses.

    Spelled out rather than `**fields`, because a protocol that accepts
    anything matches nothing: `**fields: Any` is not structurally compatible
    with a keyword-only signature, and typing it loosely here would have moved
    the mistake to runtime.
    """

    async def place(
        self,
        *,
        user_id: int,
        jalali_year: int,
        plan_id: str,
        plan_name_fa: str,
        duration_days: int,
        list_price: Money,
        total: Money,
        traffic_mib: int | None = ...,
        device_limit: int = ...,
        source: OrderSource = ...,
    ) -> Any: ...


class Provisioning(Protocol):
    async def provision(
        self,
        order_id: str,
        *,
        country_code: str | None = None,
        reseller_id: str | None = None,
        allowed_node_ids: frozenset[str] | None = None,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class ResellerSale:
    subscription_id: str
    subscription_url: str | None
    remote_username: str
    expires_at: Any
    charged: Money
    balance_after: int


class ResellerSalesService:
    def __init__(
        self,
        *,
        resellers: ResellerService,
        plans: PlanCatalogue,
        orders: Orders,
        provisioning: Provisioning,
        jalali_year: int,
    ) -> None:
        self._resellers = resellers
        self._plans = plans
        self._orders = orders
        self._provisioning = provisioning
        self._jalali_year = jalali_year

    async def sell(
        self,
        *,
        reseller_id: uuid.UUID,
        plan_id: uuid.UUID,
        note_fa: str = "",
        country_code: str | None = None,
    ) -> ResellerSale:
        reseller = await self._resellers.get(reseller_id)
        if not reseller.status.may_provision:
            raise ResellerSuspended("This reseller account cannot sell right now.")

        plan = await self._plans.get(plan_id)
        if plan is None:
            raise LookupError("No such package.")

        cost = reseller.price_for(plan_id, plan.base_price)

        # Raises InsufficientCredit, before an order exists and before anything
        # is created on a panel. A reseller who cannot pay must not end up with
        # a half-finished sale in their list.
        after = await self._resellers.charge_for_sale(
            reseller_id,
            amount=cost,
            description_fa=f"فروش {plan.name_fa}" + (f" — {note_fa}" if note_fa else ""),
        )

        order = await self._orders.place(
            # Attributed to the reseller's own account, because their customer
            # is not a user of this platform.
            user_id=_owner_id(reseller),
            jalali_year=self._jalali_year,
            plan_id=str(plan_id),
            plan_name_fa=plan.name_fa,
            duration_days=plan.duration_days,
            list_price=plan.base_price,
            total=cost,
            traffic_mib=_traffic_of(plan),
            device_limit=plan.device_limit,
            source=OrderSource.RESELLER,
        )

        try:
            subscription = await self._provisioning.provision(
                order.id,
                country_code=country_code,
                reseller_id=str(reseller_id),
                allowed_node_ids=reseller.allowed_node_ids or None,
            )
        except Exception:
            # Money back. The charge and the refund both stay on the ledger:
            # a reseller reconciling their balance is better served by two
            # honest rows than by one that quietly vanished.
            logger.info(
                "reseller.sale_failed", reseller_id=str(reseller_id), order_id=order.id
            )
            await self._resellers.refund_sale(
                reseller_id,
                amount=cost,
                description_fa="بازگشت اعتبار — فروش ناموفق",
                reference=order.id,
            )
            raise

        return ResellerSale(
            subscription_id=subscription.id,
            subscription_url=subscription.subscription_url,
            remote_username=subscription.remote_username,
            expires_at=subscription.expires_at,
            charged=cost,
            balance_after=after.balance_amount,
        )

    async def price_list(self, reseller_id: uuid.UUID, plans: Sequence[Any]) -> list[dict[str, Any]]:
        """Every package with all three numbers on it.

        List price, what it costs this reseller, and what they have decided to
        charge - because a reseller choosing what to sell is comparing their
        margin, and making them hold two screens side by side to do it is how
        they end up pricing from memory.
        """
        reseller = await self._resellers.get(reseller_id)
        rows: list[dict[str, Any]] = []
        for plan in plans:
            listed = plan.base_price
            rows.append(
                {
                    "plan_id": str(plan.id),
                    "name": plan.name_fa,
                    "duration_days": plan.duration_days,
                    "list_price": listed.amount,
                    "cost": reseller.price_for(plan.id, listed).amount,
                    "retail": reseller.retail_price_for(plan.id, listed).amount,
                }
            )
        return rows


def _owner_id(reseller: Reseller) -> int:
    """A stable integer for orders sold by this reseller.

    Orders key on a Telegram id, and a reseller's customer has none that this
    platform knows. So their sales are attributed to the reseller instead, and
    this derives a per-reseller integer from their id.

    **Negative on purpose.** Telegram user ids are positive, and older accounts
    have only eight digits - so folding a UUID into a positive range would
    eventually land on a real customer's id and file a reseller's orders under
    a stranger's account, where that stranger would see them. Negative ids
    cannot collide with any customer, and are visibly not a real one to anyone
    reading a row.

    The authoritative attribution is `subscriptions.reseller_id`. This only has
    to be stable and unmistakable.
    """
    return -(int(reseller.id.int % 1_000_000_000) + 1)


def _traffic_of(plan: Any) -> int | None:
    gib = getattr(plan, "quota_gib", None)
    return None if gib is None else int(gib) * 1024


__all__ = ["NodeNotAllowed", "ResellerSale", "ResellerSalesService"]
