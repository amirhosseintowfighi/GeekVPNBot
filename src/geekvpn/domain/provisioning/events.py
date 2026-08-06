"""Provisioning domain events.

Convention as everywhere else: ``<context>.<thing>.<past_tense>.v<N>``, and
amounts travel as plain integers of Toman rather than ``Money`` objects, so the
wire format does not depend on a class definition that will drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from geekvpn.domain.base.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPlaced(DomainEvent):
    name: ClassVar[str] = "provisioning.order.placed.v1"

    order_id: str
    number: str
    user_id: int
    plan_id: str
    total: int
    is_renewal: bool

    def payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "number": self.number,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "total": self.total,
            "is_renewal": self.is_renewal,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPaid(DomainEvent):
    name: ClassVar[str] = "provisioning.order.paid.v1"

    order_id: str
    user_id: int
    total: int

    def payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderProvisioned(DomainEvent):
    name: ClassVar[str] = "provisioning.order.provisioned.v1"

    order_id: str
    user_id: int
    subscription_id: str

    def payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "subscription_id": self.subscription_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderFailed(DomainEvent):
    """Money was taken but no working account exists. Always actionable."""

    name: ClassVar[str] = "provisioning.order.failed.v1"

    order_id: str
    user_id: int
    reason: str

    def payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelled(DomainEvent):
    name: ClassVar[str] = "provisioning.order.cancelled.v1"

    order_id: str
    user_id: int

    def payload(self) -> dict[str, Any]:
        return {"order_id": self.order_id, "user_id": self.user_id}


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionActivated(DomainEvent):
    name: ClassVar[str] = "provisioning.subscription.activated.v1"

    subscription_id: str
    user_id: int
    plan_id: str
    expires_at: str

    def payload(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionRenewed(DomainEvent):
    name: ClassVar[str] = "provisioning.subscription.renewed.v1"

    subscription_id: str
    user_id: int
    expires_at: str
    added_days: int

    def payload(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "expires_at": self.expires_at,
            "added_days": self.added_days,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionExpired(DomainEvent):
    name: ClassVar[str] = "provisioning.subscription.expired.v1"

    subscription_id: str
    user_id: int

    def payload(self) -> dict[str, Any]:
        return {"subscription_id": self.subscription_id, "user_id": self.user_id}


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionExhausted(DomainEvent):
    name: ClassVar[str] = "provisioning.subscription.exhausted.v1"

    subscription_id: str
    user_id: int
    used_mib: int

    def payload(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "used_mib": self.used_mib,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionSuspended(DomainEvent):
    name: ClassVar[str] = "provisioning.subscription.suspended.v1"

    subscription_id: str
    user_id: int
    reason_fa: str

    def payload(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "reason_fa": self.reason_fa,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscriptionRevokedEvent(DomainEvent):
    name: ClassVar[str] = "provisioning.subscription.revoked.v1"

    subscription_id: str
    user_id: int
    reason_fa: str

    def payload(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "reason_fa": self.reason_fa,
        }


__all__ = [
    "OrderCancelled",
    "OrderFailed",
    "OrderPaid",
    "OrderPlaced",
    "OrderProvisioned",
    "SubscriptionActivated",
    "SubscriptionExhausted",
    "SubscriptionExpired",
    "SubscriptionRenewed",
    "SubscriptionRevokedEvent",
    "SubscriptionSuspended",
]
