"""Admin command objects.

Every mutation is a typed command rather than a long keyword-argument list.
Three reasons this pays for itself:

* A plan has eighteen fields. A positional or loosely-typed call site is a bug
  waiting for the day someone swaps `quota_gib` and `duration_days`.
* The API schema, the service signature and the audit metadata all derive from
  the same shape, so they cannot drift.
* `None` becomes meaningful: on an update command it means "leave alone",
  which is what a PATCH-style admin form actually needs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    DiscountKind,
    PlanType,
    ProductTier,
)


#: Sentinel for "field not supplied" on update commands, so that an explicit
#: `None` (meaning "clear this value") stays distinguishable from an omission.
class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class CreateCategoryCommand:
    slug: str
    name_fa: str
    name_en: str | None = None
    description_fa: str | None = None
    icon: str | None = None
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class UpdateCategoryCommand:
    name_fa: str | None = None
    name_en: str | None = None
    description_fa: str | None = None
    icon: str | None = None
    sort_order: int | None = None


@dataclass(frozen=True, slots=True)
class CreateProductCommand:
    category_id: uuid.UUID
    slug: str
    tier: ProductTier
    name_fa: str
    tagline_fa: str | None = None
    description_fa: str | None = None
    features_fa: tuple[str, ...] = ()
    icon: str | None = None
    badge_fa: str | None = None
    accent_color: str | None = None
    sort_order: int = 0
    is_featured: bool = False
    panel_id: uuid.UUID | None = None
    node_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateProductCommand:
    name_fa: str | None = None
    tagline_fa: str | None = None
    description_fa: str | None = None
    features_fa: tuple[str, ...] | None = None
    icon: str | None = None
    badge_fa: str | None = None
    accent_color: str | None = None
    sort_order: int | None = None
    is_featured: bool | None = None
    category_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CreatePlanCommand:
    """A ready-made package.

    There is deliberately no "traffic top-up" command anywhere in this module.
    Packages are bought whole; a customer who wants more buys the next package
    up. That decision is enforced by the domain model, and this is where it
    becomes visible to the admin panel: the only way to give a customer more
    traffic is to define a package that contains it.
    """

    product_id: uuid.UUID
    slug: str
    plan_type: PlanType
    name_fa: str
    duration_days: int
    base_price: int
    quota_gib: int | None = None
    daily_quota_gib: int | None = None
    device_limit: int = 1
    description_fa: str | None = None
    badge_fa: str | None = None
    compare_at_price: int | None = None
    min_price: int | None = None
    cashback_bps: int = 0
    max_per_user: int | None = None
    sort_order: int = 0
    is_featured: bool = False


@dataclass(frozen=True, slots=True)
class UpdatePlanCommand:
    name_fa: str | None = None
    description_fa: str | None = None
    badge_fa: str | None = None
    base_price: int | None = None
    compare_at_price: int | _Unset | None = UNSET
    min_price: int | None = None
    cashback_bps: int | None = None
    max_per_user: int | _Unset | None = UNSET
    device_limit: int | None = None
    sort_order: int | None = None
    is_featured: bool | None = None


@dataclass(frozen=True, slots=True)
class ScopeCommand:
    plan_ids: tuple[uuid.UUID, ...] = ()
    product_ids: tuple[uuid.UUID, ...] = ()
    tiers: tuple[ProductTier, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateCouponCommand:
    code: str
    kind: CouponKind
    discount_kind: DiscountKind
    discount_value: int
    max_discount: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    scope: ScopeCommand = field(default_factory=ScopeCommand)
    description_fa: str | None = None
    max_redemptions: int | None = None
    max_per_user: int = 1
    min_order_amount: int = 0
    target_user_id: uuid.UUID | None = None
    stacks_with_campaign: bool = False
    first_purchase_only: bool = False


@dataclass(frozen=True, slots=True)
class CreateCampaignCommand:
    slug: str
    kind: CampaignKind
    name_fa: str
    discount_kind: DiscountKind
    discount_value: int
    max_discount: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    scope: ScopeCommand = field(default_factory=ScopeCommand)
    description_fa: str | None = None
    banner_url: str | None = None
    max_redemptions: int | None = None
    priority: int = 0
