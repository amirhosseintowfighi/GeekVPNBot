"""Catalog and pricing: what we sell, and what it costs.

This bounded context owns the storefront and the money arithmetic. It does not
know how a subscription is provisioned (that is `domain.panels`) and it does not
know how money arrives (that is Phase 5, payments).

The shape of the catalogue follows a deliberate product decision: customers buy
**ready-made packages**. They pick "one month, 50 GB" and pay. There is no
mid-cycle top-up, no build-your-own calculator, no per-gigabyte meter running in
the background. That decision is enforced structurally - a `Plan` is an
immutable, fully-priced bundle - rather than by convention.
"""

from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    DiscountKind,
    PlanType,
    ProductTier,
    PublicationState,
    RewardTrigger,
)
from geekvpn.domain.catalog.errors import (
    CampaignNotRunning,
    CatalogError,
    CouponExhausted,
    CouponExpired,
    CouponNotApplicable,
    PlanNotPurchasable,
    PriceFloorBreached,
)
from geekvpn.domain.catalog.money import Money, Toman

__all__ = [
    "CampaignKind",
    "CampaignNotRunning",
    "CatalogError",
    "CouponExhausted",
    "CouponExpired",
    "CouponKind",
    "CouponNotApplicable",
    "DiscountKind",
    "Money",
    "PlanNotPurchasable",
    "PlanType",
    "PriceFloorBreached",
    "ProductTier",
    "PublicationState",
    "RewardTrigger",
    "Toman",
]
