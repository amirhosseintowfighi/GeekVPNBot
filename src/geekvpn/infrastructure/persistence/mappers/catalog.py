"""Mappers between catalog tables and catalog aggregates.

The domain never imports SQLAlchemy and the models never import aggregates;
this module is the only place that knows both. That is what allows the entire
pricing engine to be tested with plain objects and no database.
"""

from __future__ import annotations

import uuid
from typing import Any

from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.category import Category
from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    DiscountKind,
    PlanType,
    ProductTier,
    PublicationState,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.catalog.scope import PromotionScope
from geekvpn.domain.catalog.window import TimeWindow
from geekvpn.infrastructure.persistence.models.catalog import (
    CampaignModel,
    CategoryModel,
    CouponModel,
    PlanModel,
    ProductModel,
)

# -- shared value objects --------------------------------------------------


def scope_to_json(scope: PromotionScope) -> dict[str, Any]:
    return {
        "plan_ids": sorted(str(v) for v in scope.plan_ids),
        "product_ids": sorted(str(v) for v in scope.product_ids),
        "tiers": sorted(t.value for t in scope.tiers),
    }


def scope_from_json(raw: dict[str, Any] | None) -> PromotionScope:
    raw = raw or {}
    return PromotionScope(
        plan_ids=frozenset(uuid.UUID(v) for v in raw.get("plan_ids", [])),
        product_ids=frozenset(uuid.UUID(v) for v in raw.get("product_ids", [])),
        tiers=frozenset(ProductTier(v) for v in raw.get("tiers", [])),
    )


def discount_from_row(kind: str, value: int, max_discount: int | None) -> Discount:
    # Discount.value is always a plain int: basis points for a percentage,
    # Toman for a fixed amount. The discriminator is `kind`, not the type.
    return Discount(
        kind=DiscountKind(kind),
        value=value,
        max_discount=Money(max_discount) if max_discount is not None else None,
    )


def discount_to_row(discount: Discount) -> tuple[str, int, int | None]:
    return (
        discount.kind.value,
        int(discount.value),
        discount.max_discount.amount if discount.max_discount else None,
    )


# -- category --------------------------------------------------------------


def category_to_domain(row: CategoryModel) -> Category:
    return Category(
        category_id=row.id,
        slug=row.slug,
        name_fa=row.name_fa,
        name_en=row.name_en,
        description_fa=row.description_fa,
        icon=row.icon,
        sort_order=row.sort_order,
        state=PublicationState(row.state),
        created_at=row.created_at,
    )


def category_to_row(category: Category, row: CategoryModel | None = None) -> CategoryModel:
    row = row or CategoryModel(id=category.id)
    row.slug = category.slug
    row.name_fa = category.name_fa
    row.name_en = category.name_en
    row.description_fa = category.description_fa
    row.icon = category.icon
    row.sort_order = category.sort_order
    row.state = category.state.value
    return row


# -- product ---------------------------------------------------------------


def product_to_domain(row: ProductModel) -> Product:
    return Product(
        product_id=row.id,
        category_id=row.category_id,
        slug=row.slug,
        tier=ProductTier(row.tier),
        name_fa=row.name_fa,
        tagline_fa=row.tagline_fa,
        description_fa=row.description_fa,
        features_fa=tuple(row.features_fa or ()),
        icon=row.icon,
        badge_fa=row.badge_fa,
        accent_color=row.accent_color,
        sort_order=row.sort_order,
        state=PublicationState(row.state),
        panel_id=row.panel_id,
        node_tags=tuple(row.node_tags or ()),
        is_featured=row.is_featured,
        created_at=row.created_at,
    )


def product_to_row(product: Product, row: ProductModel | None = None) -> ProductModel:
    row = row or ProductModel(id=product.id)
    row.category_id = product.category_id
    row.slug = product.slug
    row.tier = product.tier.value
    row.name_fa = product.name_fa
    row.tagline_fa = product.tagline_fa
    row.description_fa = product.description_fa
    row.features_fa = list(product.features_fa)
    row.icon = product.icon
    row.badge_fa = product.badge_fa
    row.accent_color = product.accent_color
    row.sort_order = product.sort_order
    row.state = product.state.value
    row.panel_id = product.panel_id
    row.node_tags = list(product.node_tags)
    row.is_featured = product.is_featured
    return row


# -- plan ------------------------------------------------------------------


def plan_to_domain(row: PlanModel) -> Plan:
    return Plan(
        plan_id=row.id,
        product_id=row.product_id,
        slug=row.slug,
        plan_type=PlanType(row.plan_type),
        name_fa=row.name_fa,
        description_fa=row.description_fa,
        badge_fa=row.badge_fa,
        duration_days=row.duration_days,
        quota_gib=row.quota_gib,
        daily_quota_gib=row.daily_quota_gib,
        device_limit=row.device_limit,
        base_price=Money(row.base_price),
        compare_at_price=(
            Money(row.compare_at_price) if row.compare_at_price is not None else None
        ),
        min_price=Money(row.min_price),
        cashback_bps=row.cashback_bps,
        max_per_user=row.max_per_user,
        sort_order=row.sort_order,
        state=PublicationState(row.state),
        is_featured=row.is_featured,
        created_at=row.created_at,
    )


def plan_to_row(plan: Plan, row: PlanModel | None = None) -> PlanModel:
    row = row or PlanModel(id=plan.id)
    row.product_id = plan.product_id
    row.slug = plan.slug
    row.plan_type = plan.plan_type.value
    row.name_fa = plan.name_fa
    row.description_fa = plan.description_fa
    row.badge_fa = plan.badge_fa
    row.duration_days = plan.duration_days
    row.quota_gib = plan.quota_gib
    row.daily_quota_gib = plan.daily_quota_gib
    row.device_limit = plan.device_limit
    row.base_price = plan.base_price.amount
    row.compare_at_price = plan.compare_at_price.amount if plan.compare_at_price else None
    row.min_price = plan.min_price.amount
    row.cashback_bps = plan.cashback_bps
    row.max_per_user = plan.max_per_user
    row.sort_order = plan.sort_order
    row.state = plan.state.value
    row.is_featured = plan.is_featured
    return row


# -- coupon ----------------------------------------------------------------


def coupon_to_domain(row: CouponModel) -> Coupon:
    return Coupon(
        coupon_id=row.id,
        code=row.code,
        kind=CouponKind(row.kind),
        discount=discount_from_row(row.discount_kind, row.discount_value, row.max_discount),
        window=TimeWindow(starts_at=row.starts_at, ends_at=row.ends_at),
        scope=scope_from_json(row.scope),
        description_fa=row.description_fa,
        max_redemptions=row.max_redemptions,
        max_per_user=row.max_per_user,
        redemption_count=row.redemption_count,
        min_order_amount=Money(row.min_order_amount),
        target_user_id=row.target_user_id,
        stacks_with_campaign=row.stacks_with_campaign,
        first_purchase_only=row.first_purchase_only,
        state=PublicationState(row.state),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def coupon_to_row(coupon: Coupon, row: CouponModel | None = None) -> CouponModel:
    row = row or CouponModel(id=coupon.id)
    kind, value, cap = discount_to_row(coupon.discount)
    row.code = coupon.code
    row.kind = coupon.kind.value
    row.description_fa = coupon.description_fa
    row.discount_kind = kind
    row.discount_value = value
    row.max_discount = cap
    row.starts_at = coupon.window.starts_at
    row.ends_at = coupon.window.ends_at
    row.scope = scope_to_json(coupon.scope)
    row.max_redemptions = coupon.max_redemptions
    row.max_per_user = coupon.max_per_user
    row.redemption_count = coupon.redemption_count
    row.min_order_amount = coupon.min_order_amount.amount if coupon.min_order_amount else 0
    row.target_user_id = coupon.target_user_id
    row.stacks_with_campaign = coupon.stacks_with_campaign
    row.first_purchase_only = coupon.first_purchase_only
    row.state = coupon.state.value
    row.created_by = coupon.created_by
    return row


# -- campaign --------------------------------------------------------------


def campaign_to_domain(row: CampaignModel) -> Campaign:
    return Campaign(
        campaign_id=row.id,
        slug=row.slug,
        kind=CampaignKind(row.kind),
        name_fa=row.name_fa,
        description_fa=row.description_fa,
        banner_url=row.banner_url,
        discount=discount_from_row(row.discount_kind, row.discount_value, row.max_discount),
        window=TimeWindow(starts_at=row.starts_at, ends_at=row.ends_at),
        scope=scope_from_json(row.scope),
        max_redemptions=row.max_redemptions,
        redemption_count=row.redemption_count,
        priority=row.priority,
        state=PublicationState(row.state),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def campaign_to_row(campaign: Campaign, row: CampaignModel | None = None) -> CampaignModel:
    row = row or CampaignModel(id=campaign.id)
    kind, value, cap = discount_to_row(campaign.discount)
    row.slug = campaign.slug
    row.kind = campaign.kind.value
    row.name_fa = campaign.name_fa
    row.description_fa = campaign.description_fa
    row.banner_url = campaign.banner_url
    row.discount_kind = kind
    row.discount_value = value
    row.max_discount = cap
    row.starts_at = campaign.window.starts_at
    row.ends_at = campaign.window.ends_at
    row.scope = scope_to_json(campaign.scope)
    row.max_redemptions = campaign.max_redemptions
    row.redemption_count = campaign.redemption_count
    row.priority = campaign.priority
    row.state = campaign.state.value
    row.created_by = campaign.created_by
    return row
