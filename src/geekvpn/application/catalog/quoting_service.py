"""Quoting: what does this cost, for this customer, right now.

Split from the storefront service because quoting is the write-adjacent path -
it is what the order flow calls immediately before taking money, and it must
validate coupons strictly. The storefront path, by contrast, prices everything
optimistically and must never raise.
"""

from __future__ import annotations

import uuid

from geekvpn.application.catalog.dto import CouponPreview, QuoteView
from geekvpn.application.catalog.policy_provider import PricingPolicyProvider
from geekvpn.application.ports.catalog import (
    CampaignRepository,
    CouponRepository,
    PlanRepository,
    ProductRepository,
)
from geekvpn.application.ports.clock import Clock
from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.catalog.coupon import Coupon, normalise_code
from geekvpn.domain.catalog.errors import CatalogError, CatalogValidationError
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.pricing import PriceQuote, PricingContext, quote_plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.catalog.rewards import LoyaltyTier


class QuotingService:
    """Prices a single plan, with or without a coupon."""

    def __init__(
        self,
        *,
        plans: PlanRepository,
        products: ProductRepository,
        campaigns: CampaignRepository,
        coupons: CouponRepository,
        policies: PricingPolicyProvider,
        clock: Clock,
    ) -> None:
        self._plans = plans
        self._products = products
        self._campaigns = campaigns
        self._coupons = coupons
        self._policies = policies
        self._clock = clock

    async def quote(
        self,
        *,
        plan_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        coupon_code: str | None = None,
        loyalty_tier: LoyaltyTier = LoyaltyTier.BRONZE,
        is_first_purchase: bool = False,
        referrer_id: uuid.UUID | None = None,
        enforce_purchasable: bool = True,
    ) -> PriceQuote:
        """Full quote. Raises if the coupon is unusable."""
        plan, product = await self._load(plan_id)
        now = self._clock.now()
        policy = await self._policies.load()
        running = list(await self._campaigns.list_running(now=now))

        coupon, redemptions = await self._resolve_coupon(coupon_code, user_id)

        context = PricingContext(
            now=now,
            user_id=user_id,
            loyalty_tier=loyalty_tier,
            is_first_purchase=is_first_purchase,
            referrer_id=referrer_id,
            coupon_redemptions_by_user=redemptions,
        )
        return quote_plan(
            plan=plan,
            product=product,
            context=context,
            policy=policy,
            campaigns=running,
            coupon=coupon,
            enforce_purchasable=enforce_purchasable,
        )

    async def quote_view(self, **kwargs: object) -> QuoteView:
        return QuoteView.of(await self.quote(**kwargs))  # type: ignore[arg-type]

    async def preview_coupon(
        self,
        *,
        plan_id: uuid.UUID,
        code: str,
        user_id: uuid.UUID | None = None,
        loyalty_tier: LoyaltyTier = LoyaltyTier.BRONZE,
        is_first_purchase: bool = False,
    ) -> CouponPreview:
        """Try a code and report the outcome without raising.

        The bot calls this while the customer is still typing. A rejection here
        is a normal conversational outcome, not an error, so the specific
        Persian reason is returned as data rather than thrown as an exception
        that the handler would have to catch and translate anyway.
        """
        try:
            normalised = normalise_code(code)
        except CatalogValidationError:
            return CouponPreview.rejected(code=code, message_fa="فرمت این کد درست نیست.")

        baseline = await self.quote(
            plan_id=plan_id,
            user_id=user_id,
            loyalty_tier=loyalty_tier,
            is_first_purchase=is_first_purchase,
        )

        try:
            discounted = await self.quote(
                plan_id=plan_id,
                user_id=user_id,
                coupon_code=normalised,
                loyalty_tier=loyalty_tier,
                is_first_purchase=is_first_purchase,
            )
        except CatalogError as exc:
            return CouponPreview.rejected(code=normalised, message_fa=exc.message)

        saving = baseline.total - discounted.total
        if saving.is_zero:
            return CouponPreview.rejected(
                code=normalised,
                message_fa="این کد روی قیمت فعلی تخفیفی ایجاد نمی‌کند.",
            )
        return CouponPreview.accepted(code=normalised, discount=saving, total=discounted.total)

    # -- internals ---------------------------------------------------------

    async def _load(self, plan_id: uuid.UUID) -> tuple[Plan, Product]:
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise NotFoundError("Plan not found.", plan_id=str(plan_id))
        product = await self._products.get(plan.product_id)
        if product is None:  # pragma: no cover - foreign key makes this impossible
            raise NotFoundError("Product not found.", product_id=str(plan.product_id))
        return plan, product

    async def _resolve_coupon(
        self, code: str | None, user_id: uuid.UUID | None
    ) -> tuple[Coupon | None, int]:
        if not code:
            return None, 0
        coupon = await self._coupons.get_by_code(normalise_code(code))
        if coupon is None:
            # Same wording as an expired code, so a probe cannot distinguish a
            # real-but-unusable code from one that never existed.
            raise NotFoundError("This code is not valid.", code=code)
        redemptions = 0
        if user_id is not None:
            redemptions = await self._coupons.redemption_count_for_user(coupon.id, user_id)
        return coupon, redemptions
