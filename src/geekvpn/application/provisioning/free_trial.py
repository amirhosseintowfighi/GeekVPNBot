"""The Android app's free trial: a small tunnel and direct service, once.

A trial is an ordinary order that costs nothing, so everything after it - the
panel account, the subscription link, the expiry job, the operator's retry
button - is the path a purchase takes. It borrows a real published plan for
each tier, because the plan decides the product and the product decides the
tier the app shows; only the size and the length are the trial's own.

Two steps, with a commit between them in the caller:

1. `place` records the claim and the paid orders. After that commit the trial
   is owed, and a panel that fails is the retry queue's problem rather than a
   lost claim.
2. `deliver` provisions each order and returns what came up.

The orders are `OrderSource.TRIAL`, which first-purchase pricing and referral
conversion leave out: a trial is not a purchase.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from geekvpn.application.ports.catalog import PlanRepository, ProductRepository
from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.order_service import OrderService
from geekvpn.application.provisioning.ports import FreeTrialRepository, OrderRepository
from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.domain.catalog.enums import ProductTier
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.provisioning.enums import OrderSource
from geekvpn.domain.provisioning.errors import (
    FreeTrialAlreadyClaimed,
    FreeTrialUnavailable,
    ProvisioningError,
)
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription

_log = logging.getLogger(__name__)

#: What the trial gives, per tier.
TRIAL_TRAFFIC_MIB = 50
TRIAL_DURATION_DAYS = 2
TRIAL_DEVICE_LIMIT = 1
#: The tiers a trial covers, each its own service.
TRIAL_TIERS: tuple[ProductTier, ...] = (ProductTier.TUNNEL, ProductTier.DIRECT)
TRIAL_NAME_FA = "تست رایگان"


@dataclass(frozen=True, slots=True)
class TrialOffer:
    """Whether this customer can still have the trial, and what it is."""

    available: bool
    traffic_mib: int = TRIAL_TRAFFIC_MIB
    duration_days: int = TRIAL_DURATION_DAYS


@dataclass(frozen=True, slots=True)
class TrialDelivery:
    subscriptions: tuple[Subscription, ...]
    #: Orders whose panel account did not come up. They stay in the retry
    #: queue, so the customer is told the service is coming, not that it failed.
    pending: int


class FreeTrial:
    def __init__(
        self,
        *,
        claims: FreeTrialRepository,
        products: ProductRepository,
        plans: PlanRepository,
        orders: OrderService,
        order_repository: OrderRepository,
        provisioning: ProvisioningService,
        clock: Clock,
        jalali_year: int,
    ) -> None:
        self._claims = claims
        self._products = products
        self._plans = plans
        self._orders = orders
        self._order_repository = order_repository
        self._provisioning = provisioning
        self._clock = clock
        self._jalali_year = jalali_year

    async def offer(self, user_id: int) -> TrialOffer:
        """Available only to someone who has not had it and while a plan exists."""
        if await self._claims.has_claimed(user_id):
            return TrialOffer(available=False)
        return TrialOffer(available=bool(await self._plans_by_tier()))

    async def place(self, user_id: int) -> list[Order]:
        """Claim the trial and record one paid order per tier.

        :raises FreeTrialUnavailable: no tier has a published plan.
        :raises FreeTrialAlreadyClaimed: this customer has had it.
        """
        chosen = await self._plans_by_tier()
        if not chosen:
            raise FreeTrialUnavailable("No plan is available for a free trial.")
        now = self._clock.now()
        if not await self._claims.claim(user_id, at=now):
            raise FreeTrialAlreadyClaimed(
                "This customer has already had the free trial.", user_id=user_id
            )

        placed: list[Order] = []
        for product, plan in chosen:
            order = await self._orders.place(
                user_id=user_id,
                jalali_year=self._jalali_year,
                plan_id=str(plan.id),
                plan_name_fa=TRIAL_NAME_FA,
                duration_days=TRIAL_DURATION_DAYS,
                list_price=Money(0),
                total=Money(0),
                product_id=str(product.id),
                traffic_mib=TRIAL_TRAFFIC_MIB,
                device_limit=TRIAL_DEVICE_LIMIT,
                source=OrderSource.TRIAL,
            )
            # Nothing to pay, so nothing will ever approve a payment for it.
            order.mark_paid(at=now)
            await self._order_repository.update(order)
            placed.append(order)
        return placed

    async def deliver(self, orders: Sequence[Order]) -> TrialDelivery:
        """Provision each order; a failure leaves that order to the retry queue."""
        delivered: list[Subscription] = []
        pending = 0
        for order in orders:
            try:
                delivered.append(await self._provisioning.provision(order.id))
            except ProvisioningError as error:
                pending += 1
                _log.warning("free_trial.delivery_pending order=%s reason=%s", order.id, error.code)
        return TrialDelivery(subscriptions=tuple(delivered), pending=pending)

    async def _plans_by_tier(self) -> list[tuple[Product, Plan]]:
        """For each trial tier, the plan a trial order is filed under.

        The featured product first, then the catalogue's own order; within it,
        the shortest and then cheapest plan - the one a trial most resembles.
        A tier with nothing published is skipped rather than failing the rest.
        """
        products = await self._products.list_all(published_only=True)
        chosen: list[tuple[Product, Plan]] = []
        for tier in TRIAL_TIERS:
            candidates = sorted(
                (product for product in products if product.tier is tier),
                key=lambda product: (not product.is_featured, product.sort_order),
            )
            for product in candidates:
                plans = [
                    plan
                    for plan in await self._plans.list_for_product(product.id, published_only=True)
                    if plan.is_visible
                ]
                if plans:
                    plan = min(plans, key=lambda p: (p.duration_days, p.base_price.amount))
                    chosen.append((product, plan))
                    break
        return chosen


__all__ = [
    "TRIAL_DURATION_DAYS",
    "TRIAL_TIERS",
    "TRIAL_TRAFFIC_MIB",
    "FreeTrial",
    "TrialDelivery",
    "TrialOffer",
]
