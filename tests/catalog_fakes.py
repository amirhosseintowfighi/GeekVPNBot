"""In-memory doubles for the catalog repositories.

These are real implementations of the repository Protocols backed by dicts, not
mocks. A mock asserts that a method was called; these let a test assert that
the *catalogue* ended up in the right state, which is what actually matters.

They are also the proof that the ports are honest: if a service can be driven
by a dict, nothing SQLAlchemy-shaped has leaked into the application layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.category import Category
from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    PlanType,
    ProductTier,
    PublicationState,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.catalog.window import TimeWindow

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
PANEL_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


class FakeClock:
    def __init__(self, moment: datetime = NOW) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class FakeAudit:
    """Collects audit entries so tests can assert they were written."""

    def __init__(self) -> None:
        self.entries: list[tuple[Any, dict[str, Any]]] = []

    async def record(self, action: Any, **kwargs: Any) -> None:
        self.entries.append((action, kwargs))

    @property
    def actions(self) -> list[str]:
        return [str(action) for action, _ in self.entries]


class _Store:
    """Shared dict-backed storage with slug lookup."""

    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Any] = {}

    async def get(self, entity_id: uuid.UUID) -> Any | None:
        return self.items.get(entity_id)

    async def get_by_slug(self, slug: str) -> Any | None:
        return next((i for i in self.items.values() if i.slug == slug), None)

    async def add(self, entity: Any) -> None:
        self.items[entity.id] = entity

    async def update(self, entity: Any) -> None:
        self.items[entity.id] = entity


class FakeCategoryRepository(_Store):
    async def list_all(self, *, published_only: bool = False) -> list[Category]:
        values = list(self.items.values())
        if published_only:
            values = [c for c in values if c.is_visible]
        return values


class FakeProductRepository(_Store):
    async def list_all(
        self, *, category_id: uuid.UUID | None = None, published_only: bool = False
    ) -> list[Product]:
        values = list(self.items.values())
        if category_id is not None:
            values = [p for p in values if p.category_id == category_id]
        if published_only:
            values = [p for p in values if p.is_visible]
        return values


class FakePlanRepository(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.orders_exist = False

    async def list_all(
        self, *, product_id: uuid.UUID | None = None, published_only: bool = False
    ) -> list[Plan]:
        values = list(self.items.values())
        if product_id is not None:
            values = [p for p in values if p.product_id == product_id]
        if published_only:
            values = [p for p in values if p.is_visible]
        return values

    async def has_orders(self, plan_id: uuid.UUID) -> bool:
        return self.orders_exist


class FakeCouponRepository(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.redemptions: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        self.recorded: list[dict[str, Any]] = []

    async def get_by_code(self, code: str) -> Coupon | None:
        return next((c for c in self.items.values() if c.code == code), None)

    async def list_all(
        self, *, active_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Coupon]:
        values = list(self.items.values())
        if active_only:
            values = [c for c in values if c.state is PublicationState.PUBLISHED]
        return values[offset : offset + limit]

    async def redemption_count_for_user(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return self.redemptions.get((coupon_id, user_id), 0)

    async def record_redemption(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


class FakeCampaignRepository(_Store):
    async def list_all(self, *, limit: int = 50, offset: int = 0) -> list[Campaign]:
        return list(self.items.values())[offset : offset + limit]

    async def list_running(self, *, now: datetime) -> list[Campaign]:
        return [c for c in self.items.values() if c.is_running(now)]


class FakeSettingsStore:
    """Settings reader for the pricing policy provider."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = values or {}
        self.explode = False

    async def get(self, key: str) -> Any | None:
        if self.explode:
            raise RuntimeError("settings backend is down")
        return self.values.get(key)


# -- builders ---------------------------------------------------------------
# Keyword-only with sane defaults so a test states only what it cares about.


def make_category(**kw: Any) -> Category:
    kw.setdefault("category_id", uuid.uuid4())
    kw.setdefault("slug", "vpn")
    kw.setdefault("name_fa", "اینترنت آزاد")
    kw.setdefault("state", PublicationState.PUBLISHED)
    return Category(**kw)


def make_product(**kw: Any) -> Product:
    kw.setdefault("product_id", uuid.uuid4())
    kw.setdefault("category_id", uuid.uuid4())
    kw.setdefault("slug", "geek-turbo")
    kw.setdefault("tier", ProductTier.TUNNEL)
    kw.setdefault("name_fa", "گیک توربو")
    kw.setdefault("panel_id", PANEL_ID)
    kw.setdefault("state", PublicationState.PUBLISHED)
    return Product(**kw)


def make_plan(**kw: Any) -> Plan:
    kw.setdefault("plan_id", uuid.uuid4())
    kw.setdefault("product_id", uuid.uuid4())
    kw.setdefault("slug", "geek-turbo-60")
    kw.setdefault("plan_type", PlanType.TRAFFIC)
    kw.setdefault("name_fa", "توربو ۶۰ گیگ")
    kw.setdefault("duration_days", 30)
    kw.setdefault("base_price", Money(680_000))
    kw.setdefault("quota_gib", 60)
    kw.setdefault("state", PublicationState.PUBLISHED)
    return Plan(**kw)


def running_window(now: datetime = NOW) -> TimeWindow:
    from datetime import timedelta

    return TimeWindow(starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=5))


def make_campaign(**kw: Any) -> Campaign:
    kw.setdefault("campaign_id", uuid.uuid4())
    kw.setdefault("slug", "summer-flash")
    kw.setdefault("kind", CampaignKind.SEASONAL)
    kw.setdefault("name_fa", "حراج تابستانه")
    kw.setdefault("discount", Discount.percentage(1500))
    kw.setdefault("window", running_window())
    kw.setdefault("state", PublicationState.PUBLISHED)
    return Campaign(**kw)


def make_coupon(**kw: Any) -> Coupon:
    kw.setdefault("coupon_id", uuid.uuid4())
    kw.setdefault("code", "WELCOME10")
    kw.setdefault("kind", CouponKind.PUBLIC)
    kw.setdefault("discount", Discount.percentage(1000))
    return Coupon(**kw)
