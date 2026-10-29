"""Quoting: what does this cost, for this customer, right now.

Split from the storefront service because quoting is the write-adjacent path -
it is what the order flow calls immediately before taking money, and it must
validate coupons strictly. The storefront path, by contrast, prices everything
optimistically and must never raise.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

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
from geekvpn.domain.catalog.custom_volume import (
    VolumePoint,
    custom_plan,
    price_for_volume,
    total_gib,
)
from geekvpn.domain.catalog.enums import PlanType
from geekvpn.domain.catalog.errors import CatalogError, CatalogValidationError
from geekvpn.domain.catalog.money import Money
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
        default_retail: Mapping[uuid.UUID, Money] | None = None,
    ) -> None:
        self._plans = plans
        self._products = products
        self._campaigns = campaigns
        self._coupons = coupons
        self._policies = policies
        self._clock = clock
        # The shop this service was built for. Supplied by the scope rather
        # than by each caller: `quote` is reached from four places, and one
        # that forgot would price a reseller's package at our list price on the
        # screen where their customer presses pay.
        self._default_retail = dict(default_retail or {})

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
        retail_prices: Mapping[uuid.UUID, Money] | None = None,
        custom_gib: int | None = None,
    ) -> PriceQuote:
        """Full quote. Raises if the coupon is unusable.

        With ``custom_gib`` the customer chose their own monthly volume, and
        ``plan_id`` names any package of the same kind and term; see
        `custom_package`.
        """
        retail = dict(retail_prices if retail_prices is not None else self._default_retail)
        if custom_gib is None:
            plan, product = await self._load(plan_id)
        else:
            plan, product = await self.custom_package(
                plan_id=plan_id, monthly_gib=custom_gib, retail_prices=retail
            )
            # The custom package borrows its anchor's id. Left in, the anchor's
            # retail line would replace the custom price with the anchor's.
            retail.pop(plan.id, None)
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
            # A reseller's price, when this quote is for their bot. It replaces
            # the base rather than discounting it: a different shop's price is
            # not a reduction of ours.
            retail_prices=retail,
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
        custom_gib: int | None = None,
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
            custom_gib=custom_gib,
        )

        try:
            discounted = await self.quote(
                plan_id=plan_id,
                user_id=user_id,
                coupon_code=normalised,
                loyalty_tier=loyalty_tier,
                is_first_purchase=is_first_purchase,
                custom_gib=custom_gib,
            )
        except CatalogError as exc:
            return CouponPreview.rejected(code=normalised, message_fa=exc.message)

        saving = baseline.total - discounted.total
        if saving.is_zero:
            return CouponPreview.rejected(
                code=normalised,
                message_fa="این کد روی این قیمت تخفیفی نمی‌ده.",
            )
        return CouponPreview.accepted(code=normalised, discount=saving, total=discounted.total)

    async def custom_package(
        self,
        *,
        plan_id: uuid.UUID,
        monthly_gib: int,
        retail_prices: Mapping[uuid.UUID, Money] | None = None,
    ) -> tuple[Plan, Product]:
        """The package for a volume the customer typed, priced off its siblings.

        Siblings are the published volume packages of the same category and
        term as ``plan_id``: one kind of service, one length, many sizes. Their
        prices are this shop's - a reseller's retail line where they set one -
        so a reseller's customer is quoted on the reseller's own curve.
        """
        chosen, product = await self._load(plan_id)
        if chosen.plan_type is not PlanType.TRAFFIC or chosen.quota_gib is None:
            raise CatalogValidationError("این سرویس حجم دلخواه نداره.", plan_id=str(plan_id))
        retail = retail_prices if retail_prices is not None else self._default_retail
        kin = {
            p.id: p
            for p in await self._products.list_all(
                category_id=product.category_id, published_only=True
            )
        }
        siblings = [
            p
            for p in await self._plans.list_all(published_only=True)
            if p.product_id in kin
            and p.duration_days == chosen.duration_days
            and p.plan_type is PlanType.TRAFFIC
            and p.quota_gib
        ]
        if not siblings:
            raise CatalogValidationError("این سرویس حجم دلخواه نداره.", plan_id=str(plan_id))

        smallest = min(p.quota_gib or 0 for p in siblings)
        quota = total_gib(monthly_gib, chosen.duration_days)
        if quota < smallest:
            # Said in the customer's unit. They typed a monthly figure, and
            # "at least 30GB" on a three-month term reads as a different rule.
            floor = -(-smallest * 30 // chosen.duration_days)
            raise CatalogValidationError(
                f"کمترین حجم قابل خرید {floor} گیگ در ماهه.",
                monthly_gib=monthly_gib,
                minimum=floor,
            )
        price = price_for_volume(
            [VolumePoint(p.quota_gib or 0, retail.get(p.id, p.base_price)) for p in siblings],
            quota,
        )
        anchor = max(
            (p for p in siblings if (p.quota_gib or 0) <= quota),
            key=lambda p: p.quota_gib or 0,
        )
        package = custom_plan(anchor, monthly_gib=monthly_gib, quota_gib=quota, price=price)
        return package, kin[anchor.product_id]

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
