"""Builds the whole shoppable catalogue, priced for one customer.

This is the single hottest read in the platform: every bot `/start`, every
Mini App launch, every "buy" tap. Two properties matter more than anything
else here.

**It must never raise.** A misconfigured plan must disappear from the
storefront, not take down the storefront. A customer seeing four packages
instead of five is a bug we fix on Monday; a customer seeing an error page is
a customer who bought from a competitor on Sunday.

**It must be one pass.** Campaigns and the policy are loaded once and reused
for every plan, rather than re-fetched per plan. With five products and six
packages each, the naive version is 60 round trips.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import structlog

from geekvpn.application.catalog.dto import (
    CategoryView,
    PlanView,
    ProductView,
    QuoteView,
    StorefrontView,
)
from geekvpn.application.catalog.policy_provider import PricingPolicyProvider
from geekvpn.application.ports.catalog import (
    CampaignRepository,
    CategoryRepository,
    PlanRepository,
    ProductRepository,
)
from geekvpn.application.ports.clock import Clock
from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.pricing import PricingContext, quote_plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.catalog.rewards import TIER_LABEL_FA, LoyaltyTier

logger = structlog.stdlib.get_logger(__name__)


class StorefrontService:
    def __init__(
        self,
        *,
        categories: CategoryRepository,
        products: ProductRepository,
        plans: PlanRepository,
        campaigns: CampaignRepository,
        policies: PricingPolicyProvider,
        clock: Clock,
    ) -> None:
        self._categories = categories
        self._products = products
        self._plans = plans
        self._campaigns = campaigns
        self._policies = policies
        self._clock = clock

    async def load(
        self,
        *,
        user_id: uuid.UUID | None = None,
        loyalty_tier: LoyaltyTier = LoyaltyTier.BRONZE,
        is_first_purchase: bool = False,
        referrer_id: uuid.UUID | None = None,
        wallet_balance: int = 0,
        retail_prices: Mapping[uuid.UUID, Money] | None = None,
    ) -> StorefrontView:
        now = self._clock.now()
        policy = await self._policies.load()
        running = list(await self._campaigns.list_running(now=now))

        context = PricingContext(
            now=now,
            user_id=user_id,
            loyalty_tier=loyalty_tier,
            is_first_purchase=is_first_purchase,
            referrer_id=referrer_id,
            # A reseller's storefront shows their prices, not ours. Threaded
            # through the context rather than applied afterwards so campaigns,
            # coupons and cashback all compute against the price the customer
            # is actually being shown.
            retail_prices=dict(retail_prices or {}),
        )

        categories = await self._categories.list_all(published_only=True)
        all_products = await self._products.list_all(published_only=True)
        all_plans = await self._plans.list_all(published_only=True)

        plans_by_product: dict[uuid.UUID, list[Plan]] = {}
        for plan in all_plans:
            plans_by_product.setdefault(plan.product_id, []).append(plan)

        products_by_category: dict[uuid.UUID, list[Product]] = {}
        for product in all_products:
            products_by_category.setdefault(product.category_id, []).append(product)

        category_views: list[CategoryView] = []
        for category in sorted(categories, key=lambda c: (c.sort_order, c.name_fa)):
            product_views = [
                view
                for product in sorted(
                    products_by_category.get(category.id, []),
                    key=lambda p: (p.sort_order, p.name_fa),
                )
                if (
                    view := self._product_view(
                        product,
                        plans_by_product.get(product.id, []),
                        context=context,
                        policy=policy,
                        campaigns=running,
                    )
                )
                is not None
            ]
            if product_views:
                # An empty category is visual noise; hide it rather than
                # rendering a tab that leads nowhere.
                category_views.append(
                    CategoryView(
                        id=category.id,
                        slug=category.slug,
                        name=category.name_fa,
                        description=category.description_fa,
                        icon=category.icon,
                        products=tuple(product_views),
                    )
                )

        return StorefrontView(
            categories=tuple(category_views),
            loyalty_tier=loyalty_tier.value,
            loyalty_label=TIER_LABEL_FA[loyalty_tier],
            wallet_balance=wallet_balance,
        )

    def _product_view(
        self,
        product: Product,
        plans: list[Plan],
        *,
        context: PricingContext,
        policy: object,
        campaigns: list[Campaign],
    ) -> ProductView | None:
        plan_views: list[PlanView] = []
        for plan in sorted(plans, key=lambda p: (p.sort_order, p.duration_days)):
            try:
                quote = quote_plan(
                    plan=plan,
                    product=product,
                    context=context,
                    policy=policy,  # type: ignore[arg-type]
                    campaigns=campaigns,
                )
            except Exception:
                # One broken plan must not blank the storefront. Logged loudly
                # so it surfaces in monitoring rather than staying invisible.
                logger.exception(
                    "storefront.plan_pricing_failed",
                    plan_id=str(plan.id),
                    plan_slug=plan.slug,
                )
                continue

            plan_views.append(
                PlanView(
                    id=plan.id,
                    slug=plan.slug,
                    name=plan.name_fa,
                    plan_type=plan.plan_type.value,
                    duration_days=plan.duration_days,
                    quota_gib=plan.quota_gib,
                    daily_quota_gib=plan.daily_quota_gib,
                    device_limit=plan.device_limit,
                    description=plan.description_fa,
                    badge=plan.badge_fa,
                    is_featured=plan.is_featured,
                    price=QuoteView.of(quote),
                )
            )

        if not plan_views:
            return None

        return ProductView(
            id=product.id,
            slug=product.slug,
            tier=product.tier.value,
            name=product.name_fa,
            tagline=product.tagline_fa,
            description=product.description_fa,
            features=product.features_fa,
            icon=product.icon,
            badge=product.badge_fa,
            accent_color=product.accent_color,
            is_featured=product.is_featured,
            plans=tuple(plan_views),
        )
