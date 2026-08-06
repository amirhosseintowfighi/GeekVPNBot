"""Catalog and pricing tables.

Schema decisions worth defending:

* **Money is `BigInteger`, never `NUMERIC` or float.** Every amount is an
  integer number of Toman. Toman has no subunit in practice, prices reach the
  millions, and floating-point money is how a 990,000 Toman order becomes
  989,999.9999998 on an invoice.
* **Discounts are basis points in an `Integer`.** "12.5% off" is exactly 1250.
  A `NUMERIC(5,2)` would be defensible; a float would not.
* **Scope is `JSONB`, not three join tables.** A promotion's scope is read as a
  whole set on every storefront render and is never queried element-wise, so
  three join tables would add three round trips to the hottest read in the
  platform to buy referential integrity we do not use.
* **Redemptions get their own table.** A counter column cannot answer "has this
  customer already used this code", cannot be reversed on refund, and cannot be
  audited. The counter on `catalog_coupons` is a denormalised cache of this
  table, kept for the admin grid.
* **Nothing is ever deleted.** Every aggregate has a `state` column with an
  `archived` value. A plan referenced by a historical order must remain
  readable or the invoice becomes a mystery.
* **`slug` is unique and immutable in practice.** Slugs appear in deep links
  (`t.me/GeekVPNBot?start=buy_geek-turbo-60`), so they are an external contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    DiscountKind,
    PlanType,
    ProductTier,
    PublicationState,
)
from geekvpn.infrastructure.persistence.base import Base, TimestampMixin


def _values(enum_type: type) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


class CategoryModel(TimestampMixin, Base):
    __tablename__ = "catalog_categories"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(128))
    description_fa: Mapped[str | None] = mapped_column(String(512))
    icon: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PublicationState.DRAFT.value, index=True
    )

    __table_args__ = (
        CheckConstraint(f"state IN ({_values(PublicationState)})", name="catalog_categories_state"),
    )


class ProductModel(TimestampMixin, Base):
    __tablename__ = "catalog_products"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("catalog_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tier: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    tagline_fa: Mapped[str | None] = mapped_column(String(256))
    description_fa: Mapped[str | None] = mapped_column(String(2048))
    features_fa: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    icon: Mapped[str | None] = mapped_column(String(64))
    badge_fa: Mapped[str | None] = mapped_column(String(64))
    accent_color: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PublicationState.DRAFT.value, index=True
    )

    # Deliberately not a foreign key to a panels table: panels are configured
    # in Phase 3's registry and their persistence lands in a later phase. A
    # nullable UUID keeps the binding recordable now without inventing a table
    # this phase does not own.
    panel_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    node_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint(f"tier IN ({_values(ProductTier)})", name="catalog_products_tier"),
        CheckConstraint(f"state IN ({_values(PublicationState)})", name="catalog_products_state"),
        # A product cannot be published without a panel to provision it. The
        # aggregate enforces this too; the constraint means a manual SQL fix at
        # 2am cannot bypass it.
        CheckConstraint(
            "state <> 'published' OR panel_id IS NOT NULL",
            name="catalog_products_published_requires_panel",
        ),
        Index("ix_catalog_products_category_state", "category_id", "state"),
    )


class PlanModel(TimestampMixin, Base):
    """A ready-made package.

    There is no `traffic_topup` table and no `allow_addon` column anywhere in
    this schema. Customers buy whole packages; someone who needs more buys the
    next size up. That was a deliberate product decision, and the absence of a
    column is the most durable way to record it.
    """

    __tablename__ = "catalog_plans"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("catalog_products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    plan_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    description_fa: Mapped[str | None] = mapped_column(String(1024))
    badge_fa: Mapped[str | None] = mapped_column(String(64))

    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_gib: Mapped[int | None] = mapped_column(Integer)
    daily_quota_gib: Mapped[int | None] = mapped_column(Integer)
    device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    base_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compare_at_price: Mapped[int | None] = mapped_column(BigInteger)
    min_price: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cashback_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    max_per_user: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PublicationState.DRAFT.value, index=True
    )

    __table_args__ = (
        CheckConstraint(f"plan_type IN ({_values(PlanType)})", name="catalog_plans_type"),
        CheckConstraint(f"state IN ({_values(PublicationState)})", name="catalog_plans_state"),
        CheckConstraint("base_price >= 0", name="catalog_plans_price_non_negative"),
        CheckConstraint("min_price >= 0", name="catalog_plans_floor_non_negative"),
        CheckConstraint("min_price <= base_price", name="catalog_plans_floor_below_price"),
        CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price > base_price",
            name="catalog_plans_compare_at_above_price",
        ),
        CheckConstraint(
            "duration_days > 0 AND duration_days <= 3650",
            name="catalog_plans_duration_range",
        ),
        CheckConstraint(
            "cashback_bps >= 0 AND cashback_bps <= 3000",
            name="catalog_plans_cashback_range",
        ),
        CheckConstraint("device_limit > 0", name="catalog_plans_device_limit"),
        # The three plan types are three genuinely different products, and the
        # database refuses to store a hybrid. A "traffic" plan with no quota is
        # unsellable; an "unlimited" plan with a quota is a lie.
        CheckConstraint(
            "(plan_type = 'traffic' AND quota_gib IS NOT NULL AND quota_gib > 0"
            " AND daily_quota_gib IS NULL)"
            " OR (plan_type = 'unlimited' AND quota_gib IS NULL"
            " AND daily_quota_gib IS NULL)"
            " OR (plan_type = 'duration' AND daily_quota_gib IS NOT NULL"
            " AND daily_quota_gib > 0 AND quota_gib IS NULL)",
            name="catalog_plans_type_invariants",
        ),
        Index("ix_catalog_plans_product_state", "product_id", "state"),
    )


class CouponModel(TimestampMixin, Base):
    __tablename__ = "catalog_coupons"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description_fa: Mapped[str | None] = mapped_column(String(512))

    discount_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    discount_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_discount: Mapped[int | None] = mapped_column(BigInteger)

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    max_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    redemption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_order_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    stacks_with_campaign: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_purchase_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PublicationState.PUBLISHED.value, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admins.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(CouponKind)})", name="catalog_coupons_kind"),
        CheckConstraint(
            f"discount_kind IN ({_values(DiscountKind)})",
            name="catalog_coupons_discount_kind",
        ),
        CheckConstraint(f"state IN ({_values(PublicationState)})", name="catalog_coupons_state"),
        CheckConstraint("discount_value > 0", name="catalog_coupons_discount_positive"),
        CheckConstraint(
            "discount_kind <> 'percentage' OR discount_value <= 10000",
            name="catalog_coupons_percentage_range",
        ),
        CheckConstraint("redemption_count >= 0", name="catalog_coupons_count_non_negative"),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="catalog_coupons_window_ordered",
        ),
        # A single-use code with a redemption cap above one is a configuration
        # error the aggregate silently corrects; here it simply cannot exist.
        CheckConstraint(
            "kind <> 'single_use' OR max_redemptions = 1",
            name="catalog_coupons_single_use_cap",
        ),
        CheckConstraint(
            "kind <> 'targeted' OR target_user_id IS NOT NULL",
            name="catalog_coupons_targeted_requires_user",
        ),
    )


class CouponRedemptionModel(Base):
    """One row per successful use.

    The unique constraint on (coupon, user, order) is the last line of defence
    against a double-submit racing two concurrent checkouts through the same
    single-use code.
    """

    __tablename__ = "catalog_coupon_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    coupon_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("catalog_coupons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    discount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "coupon_id", "user_id", "order_id", name="catalog_coupon_redemptions_unique"
        ),
        Index("ix_catalog_coupon_redemptions_coupon_user", "coupon_id", "user_id"),
    )


class CampaignModel(TimestampMixin, Base):
    __tablename__ = "catalog_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    description_fa: Mapped[str | None] = mapped_column(String(1024))
    banner_url: Mapped[str | None] = mapped_column(String(512))

    discount_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    discount_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_discount: Mapped[int | None] = mapped_column(BigInteger)

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PublicationState.DRAFT.value, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admins.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(CampaignKind)})", name="catalog_campaigns_kind"),
        CheckConstraint(
            f"discount_kind IN ({_values(DiscountKind)})",
            name="catalog_campaigns_discount_kind",
        ),
        CheckConstraint(f"state IN ({_values(PublicationState)})", name="catalog_campaigns_state"),
        CheckConstraint("discount_value > 0", name="catalog_campaigns_discount_positive"),
        CheckConstraint(
            "discount_kind <> 'percentage' OR discount_value <= 10000",
            name="catalog_campaigns_percentage_range",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="catalog_campaigns_window_ordered",
        ),
        # A flash sale without an end is just a price cut, and one that nobody
        # remembers to switch off.
        CheckConstraint(
            "kind <> 'flash_sale' OR ends_at IS NOT NULL",
            name="catalog_campaigns_flash_sale_needs_end",
        ),
        # Covers the storefront's hottest query: running campaigns, best first.
        Index(
            "ix_catalog_campaigns_state_priority",
            "state",
            "priority",
            "ends_at",
        ),
    )
