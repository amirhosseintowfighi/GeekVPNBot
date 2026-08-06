"""Catalog domain events.

These exist so that analytics, notifications and the marketing engine can react
without the catalogue knowing they exist. A flash sale starting should light up
a broadcast; the campaign aggregate must not import the broadcaster.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from geekvpn.domain.base.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanPublished(DomainEvent):
    name: ClassVar[str] = "catalog.plan.published.v1"

    plan_id: uuid.UUID
    product_id: uuid.UUID
    slug: str
    price: int

    def payload(self) -> dict[str, Any]:
        return {
            "plan_id": str(self.plan_id),
            "product_id": str(self.product_id),
            "slug": self.slug,
            "price": self.price,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanPriceChanged(DomainEvent):
    """Emitted on every price move so the change is auditable forever."""

    name: ClassVar[str] = "catalog.plan.price_changed.v1"

    plan_id: uuid.UUID
    old_price: int
    new_price: int
    changed_by: uuid.UUID | None

    def payload(self) -> dict[str, Any]:
        return {
            "plan_id": str(self.plan_id),
            "old_price": self.old_price,
            "new_price": self.new_price,
            "changed_by": str(self.changed_by) if self.changed_by else None,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CampaignStarted(DomainEvent):
    name: ClassVar[str] = "catalog.campaign.started.v1"

    campaign_id: uuid.UUID
    slug: str
    kind: str

    def payload(self) -> dict[str, Any]:
        return {
            "campaign_id": str(self.campaign_id),
            "slug": self.slug,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CouponRedeemed(DomainEvent):
    name: ClassVar[str] = "catalog.coupon.redeemed.v1"

    coupon_id: uuid.UUID
    code: str
    user_id: uuid.UUID
    discount: int

    def payload(self) -> dict[str, Any]:
        return {
            "coupon_id": str(self.coupon_id),
            "code": self.code,
            "user_id": str(self.user_id),
            "discount": self.discount,
        }
