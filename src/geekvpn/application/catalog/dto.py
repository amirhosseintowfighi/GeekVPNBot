"""Data transfer objects for the catalog.

These exist so the API and the bot never serialise a domain aggregate directly.
A response schema is a public contract; an aggregate is an implementation
detail that must stay free to change.

Everything customer-visible carries its Persian label already resolved. The
presentation layer should never be deciding what to call a loyalty tier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.pricing import PriceQuote, QuoteLine


@dataclass(frozen=True, slots=True)
class PriceLineView:
    kind: str
    label: str
    amount: int
    is_deduction: bool

    @classmethod
    def of(cls, line: QuoteLine) -> PriceLineView:
        return cls(
            kind=line.kind.value,
            label=line.label_fa,
            amount=line.amount.amount,
            is_deduction=line.is_deduction,
        )


@dataclass(frozen=True, slots=True)
class QuoteView:
    """A priced plan, ready to render."""

    plan_id: uuid.UUID
    product_id: uuid.UUID
    base_price: int
    total: int
    total_discount: int
    discount_percent: int
    cashback: int
    lines: tuple[PriceLineView, ...]
    compare_at_price: int | None = None
    campaign_label: str | None = None
    coupon_code: str | None = None
    flash_sale_ends_in: int | None = None

    @classmethod
    def of(cls, quote: PriceQuote) -> QuoteView:
        return cls(
            plan_id=quote.plan_id,
            product_id=quote.product_id,
            base_price=quote.base_price.amount,
            total=quote.total.amount,
            total_discount=quote.total_discount.amount,
            discount_percent=quote.discount_bps // 100,
            cashback=quote.cashback.amount,
            lines=tuple(PriceLineView.of(line) for line in quote.lines),
            compare_at_price=(quote.compare_at_price.amount if quote.compare_at_price else None),
            campaign_label=quote.campaign_label_fa,
            coupon_code=quote.coupon_code,
            flash_sale_ends_in=quote.flash_sale_ends_in,
        )


@dataclass(frozen=True, slots=True)
class PlanView:
    """One purchasable package as the storefront shows it."""

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
    price: QuoteView


@dataclass(frozen=True, slots=True)
class ProductView:
    """A branded tier with its packages already priced."""

    id: uuid.UUID
    slug: str
    tier: str
    name: str
    tagline: str | None
    description: str | None
    features: tuple[str, ...]
    icon: str | None
    badge: str | None
    accent_color: str | None
    is_featured: bool
    plans: tuple[PlanView, ...]

    @property
    def cheapest_price(self) -> int | None:
        """Drives the "from 120,000 Toman" line on a product card."""
        if not self.plans:
            return None
        return min(plan.price.total for plan in self.plans)


@dataclass(frozen=True, slots=True)
class CategoryView:
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    icon: str | None
    products: tuple[ProductView, ...]


@dataclass(frozen=True, slots=True)
class StorefrontView:
    """The entire shoppable catalogue in one payload.

    Returned whole rather than paginated. The catalogue is a few dozen rows at
    most, and the Mini App needs all of it to render tabs without a second
    round trip on a mobile connection in Iran - where that round trip is the
    difference between instant and sluggish.
    """

    categories: tuple[CategoryView, ...]
    loyalty_tier: str
    loyalty_label: str
    wallet_balance: int = 0


@dataclass(frozen=True, slots=True)
class CouponPreview:
    """Result of trying a code before committing to a purchase."""

    code: str
    is_valid: bool
    discount: int = 0
    total_after: int = 0
    message_fa: str = ""

    @classmethod
    def accepted(cls, *, code: str, discount: Money, total: Money) -> CouponPreview:
        return cls(
            code=code,
            is_valid=True,
            discount=discount.amount,
            total_after=total.amount,
            message_fa="کد تخفیف اعمال شد.",
        )

    @classmethod
    def rejected(cls, *, code: str, message_fa: str) -> CouponPreview:
        return cls(code=code, is_valid=False, message_fa=message_fa)
