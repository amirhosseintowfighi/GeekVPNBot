"""Request and response schemas for the catalog and pricing endpoints.

Money crosses the wire as an integer number of Toman, always. No decimals, no
strings, no currency object. The client formats it; the server never guesses
whether "1500" meant Toman or Rial.

Customer-facing responses carry Persian labels already resolved. The Mini App
and the bot must never be in the business of deciding what to call a discount.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    DiscountKind,
    PlanType,
    ProductTier,
)
from geekvpn.presentation.api.base_schema import ApiModel


class _Schema(ApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# -- storefront ------------------------------------------------------------


class PriceLineResponse(_Schema):
    kind: str
    label: str
    amount: int
    is_deduction: bool


class QuoteResponse(_Schema):
    plan_id: uuid.UUID
    product_id: uuid.UUID
    base_price: int
    total: int
    total_discount: int
    discount_percent: int
    cashback: int
    lines: list[PriceLineResponse]
    compare_at_price: int | None = None
    campaign_label: str | None = None
    coupon_code: str | None = None
    flash_sale_ends_in: int | None = Field(
        default=None,
        description="Seconds until the applied flash sale ends. Drives the countdown.",
    )


class PlanResponse(_Schema):
    id: uuid.UUID
    slug: str
    name: str
    plan_type: str
    duration_days: int
    quota_gib: int | None
    daily_quota_gib: int | None
    device_limit: int
    description: str | None
    badge: str | None
    is_featured: bool
    price: QuoteResponse


class ProductResponse(_Schema):
    id: uuid.UUID
    slug: str
    tier: str
    name: str
    tagline: str | None
    description: str | None
    features: list[str]
    icon: str | None
    badge: str | None
    accent_color: str | None
    is_featured: bool
    plans: list[PlanResponse]


class CategoryResponse(_Schema):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    icon: str | None
    products: list[ProductResponse]


class StorefrontResponse(_Schema):
    categories: list[CategoryResponse]
    loyalty_tier: str
    loyalty_label: str
    wallet_balance: int


class CouponPreviewRequest(_Schema):
    plan_id: uuid.UUID
    code: str = Field(min_length=3, max_length=32)


class CouponPreviewResponse(_Schema):
    code: str
    is_valid: bool
    discount: int
    total_after: int
    message: str


# -- admin: categories -----------------------------------------------------


class CategoryCreateRequest(_Schema):
    slug: str = Field(min_length=2, max_length=64)
    name_fa: str = Field(min_length=1, max_length=128)
    name_en: str | None = Field(default=None, max_length=128)
    description_fa: str | None = Field(default=None, max_length=512)
    icon: str | None = Field(default=None, max_length=64)
    sort_order: int = 0


class CategoryUpdateRequest(_Schema):
    name_fa: str | None = Field(default=None, max_length=128)
    name_en: str | None = Field(default=None, max_length=128)
    description_fa: str | None = Field(default=None, max_length=512)
    icon: str | None = Field(default=None, max_length=64)
    sort_order: int | None = None


class CategoryAdminResponse(_Schema):
    id: uuid.UUID
    slug: str
    name_fa: str
    name_en: str | None
    description_fa: str | None
    icon: str | None
    sort_order: int
    state: str


# -- admin: products -------------------------------------------------------


class ProductCreateRequest(_Schema):
    category_id: uuid.UUID
    slug: str = Field(min_length=2, max_length=64)
    tier: ProductTier
    name_fa: str = Field(min_length=1, max_length=128)
    tagline_fa: str | None = Field(default=None, max_length=256)
    description_fa: str | None = Field(default=None, max_length=2048)
    features_fa: list[str] = Field(default_factory=list, max_length=12)
    icon: str | None = Field(default=None, max_length=64)
    badge_fa: str | None = Field(default=None, max_length=64)
    accent_color: str | None = Field(default=None, max_length=32)
    sort_order: int = 0
    is_featured: bool = False
    panel_id: uuid.UUID | None = None
    node_tags: list[str] = Field(default_factory=list)


class ProductUpdateRequest(_Schema):
    name_fa: str | None = Field(default=None, max_length=128)
    tagline_fa: str | None = Field(default=None, max_length=256)
    description_fa: str | None = Field(default=None, max_length=2048)
    features_fa: list[str] | None = Field(default=None, max_length=12)
    icon: str | None = Field(default=None, max_length=64)
    badge_fa: str | None = Field(default=None, max_length=64)
    accent_color: str | None = Field(default=None, max_length=32)
    sort_order: int | None = None
    is_featured: bool | None = None
    category_id: uuid.UUID | None = None


class ProductPanelBindRequest(_Schema):
    panel_id: uuid.UUID
    node_tags: list[str] = Field(default_factory=list)


class ProductAdminResponse(_Schema):
    id: uuid.UUID
    category_id: uuid.UUID
    slug: str
    tier: str
    name_fa: str
    tagline_fa: str | None
    description_fa: str | None
    features_fa: list[str]
    icon: str | None
    badge_fa: str | None
    accent_color: str | None
    sort_order: int
    is_featured: bool
    state: str
    panel_id: uuid.UUID | None
    node_tags: list[str]
    is_provisionable: bool


# -- admin: plans ----------------------------------------------------------


class PlanCreateRequest(_Schema):
    """Define one ready-made package.

    There is no top-up endpoint anywhere in this API. Customers buy packages
    whole; the way to offer more traffic is to define a package containing it.
    """

    product_id: uuid.UUID
    slug: str = Field(min_length=2, max_length=64)
    plan_type: PlanType
    name_fa: str = Field(min_length=1, max_length=128)
    duration_days: int = Field(gt=0, le=3650)
    base_price: int = Field(ge=0)
    quota_gib: int | None = Field(default=None, gt=0)
    daily_quota_gib: int | None = Field(default=None, gt=0)
    device_limit: int = Field(default=1, gt=0, le=100)
    description_fa: str | None = Field(default=None, max_length=1024)
    badge_fa: str | None = Field(default=None, max_length=64)
    compare_at_price: int | None = Field(default=None, gt=0)
    min_price: int | None = Field(default=None, ge=0)
    cashback_bps: int = Field(default=0, ge=0, le=3000)
    max_per_user: int | None = Field(default=None, gt=0)
    sort_order: int = 0
    is_featured: bool = False


class PlanUpdateRequest(_Schema):
    name_fa: str | None = Field(default=None, max_length=128)
    description_fa: str | None = Field(default=None, max_length=1024)
    badge_fa: str | None = Field(default=None, max_length=64)
    base_price: int | None = Field(default=None, ge=0)
    compare_at_price: int | None = Field(default=None, gt=0)
    clear_compare_at_price: bool = Field(
        default=False,
        description="Remove the strike-through price. Needed because a null"
        " field means 'leave unchanged' everywhere else in this payload.",
    )
    min_price: int | None = Field(default=None, ge=0)
    cashback_bps: int | None = Field(default=None, ge=0, le=3000)
    max_per_user: int | None = Field(default=None, gt=0)
    device_limit: int | None = Field(default=None, gt=0, le=100)
    sort_order: int | None = None
    is_featured: bool | None = None


class PlanAdminResponse(_Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    slug: str
    plan_type: str
    name_fa: str
    description_fa: str | None
    badge_fa: str | None
    duration_days: int
    quota_gib: int | None
    daily_quota_gib: int | None
    device_limit: int
    base_price: int
    compare_at_price: int | None
    min_price: int
    cashback_bps: int
    max_per_user: int | None
    sort_order: int
    is_featured: bool
    state: str
    price_per_gib: int | None = None
    savings_percent: int = 0


class PublishRequest(_Schema):
    publish: bool


# -- admin: promotions -----------------------------------------------------


class ScopeRequest(_Schema):
    """Which plans a promotion touches. Empty means everything."""

    plan_ids: list[uuid.UUID] = Field(default_factory=list)
    product_ids: list[uuid.UUID] = Field(default_factory=list)
    tiers: list[ProductTier] = Field(default_factory=list)


class CouponCreateRequest(_Schema):
    code: str = Field(min_length=3, max_length=32)
    kind: CouponKind
    discount_kind: DiscountKind
    discount_value: int = Field(
        gt=0,
        description="Basis points for a percentage discount, Toman for a fixed one.",
    )
    max_discount: int | None = Field(default=None, gt=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    scope: ScopeRequest = Field(default_factory=ScopeRequest)
    description_fa: str | None = Field(default=None, max_length=512)
    max_redemptions: int | None = Field(default=None, gt=0)
    max_per_user: int = Field(default=1, gt=0)
    min_order_amount: int = Field(default=0, ge=0)
    target_user_id: uuid.UUID | None = None
    stacks_with_campaign: bool = False
    first_purchase_only: bool = False


class CouponBulkCreateRequest(_Schema):
    template: CouponCreateRequest
    count: int = Field(gt=0, le=500)
    prefix: str = Field(min_length=2, max_length=12)


class CouponAdminResponse(_Schema):
    id: uuid.UUID
    code: str
    kind: str
    description_fa: str | None
    discount_label: str
    starts_at: datetime | None
    ends_at: datetime | None
    max_redemptions: int | None
    max_per_user: int
    redemption_count: int
    remaining_redemptions: int | None
    min_order_amount: int
    target_user_id: uuid.UUID | None
    stacks_with_campaign: bool
    first_purchase_only: bool
    state: str


class CampaignCreateRequest(_Schema):
    slug: str = Field(min_length=2, max_length=64)
    kind: CampaignKind
    name_fa: str = Field(min_length=1, max_length=128)
    discount_kind: DiscountKind
    discount_value: int = Field(gt=0)
    max_discount: int | None = Field(default=None, gt=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    scope: ScopeRequest = Field(default_factory=ScopeRequest)
    description_fa: str | None = Field(default=None, max_length=1024)
    banner_url: str | None = Field(default=None, max_length=512)
    max_redemptions: int | None = Field(default=None, gt=0)
    priority: int = 0


class CampaignStateRequest(_Schema):
    state: str = Field(pattern="^(activate|pause|archive)$")


class CampaignAdminResponse(_Schema):
    id: uuid.UUID
    slug: str
    kind: str
    name_fa: str
    description_fa: str | None
    banner_url: str | None
    discount_label: str
    starts_at: datetime | None
    ends_at: datetime | None
    max_redemptions: int | None
    redemption_count: int
    remaining_stock: int | None
    priority: int
    state: str


class CampaignPerformanceResponse(_Schema):
    slug: str
    name: str
    state: str
    is_running: bool
    redemptions: int
    remaining_stock: int | None
    is_sold_out: bool
    seconds_remaining: int | None


class AdminQuoteRequest(_Schema):
    """Preview what a customer would be charged, before publishing."""

    plan_id: uuid.UUID
    coupon_code: str | None = None
    loyalty_tier: str = "bronze"
    is_first_purchase: bool = False


class DurationRungResponse(_Schema):
    """One rung of the catalogue's duration ladder.

    The panel renders the ladder before generating anything, so an operator can
    see which terms exist and what discount each carries.
    """

    days: int
    slug: str
    name_fa: str
    discount_bps: int
    badge_fa: str | None
    bonus_devices: int


class LadderGenerateRequest(_Schema):
    """Generate a whole ladder of packages from one monthly price.

    `days` narrows the ladder to the listed terms. Left out, the product gets
    the catalogue default, which omits the weekly rung - it only makes sense on
    cheap tiers.
    """

    product_id: uuid.UUID
    monthly_price: int = Field(gt=0)
    plan_type: PlanType
    slug_prefix: str = Field(min_length=2, max_length=48)
    name_prefix_fa: str = Field(min_length=1, max_length=96)
    monthly_quota_gib: int | None = Field(default=None, gt=0)
    daily_quota_gib: int | None = Field(default=None, gt=0)
    device_limit: int = Field(default=1, gt=0, le=100)
    cashback_bps: int = Field(default=0, ge=0, le=3000)
    days: list[int] | None = Field(default=None, min_length=1, max_length=8)
