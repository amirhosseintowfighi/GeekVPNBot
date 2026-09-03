"""Catalog persistence ports.

Each aggregate gets its own narrow repository. A single `CatalogRepository`
with thirty methods would be convenient to wire and miserable to fake, and it
would hide which use case actually touches which table.

The read methods come in two flavours on purpose:

* ``get_*`` returns one aggregate for mutation.
* ``list_*`` returns what the storefront or the admin grid needs.

Storefront reads are separated from admin reads because they have opposite
requirements: the storefront wants only published rows and is called on every
page view, while the admin grid wants everything including archived rows and is
called by five people a day.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.category import Category
from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product


@runtime_checkable
class CategoryRepository(Protocol):
    async def get(self, category_id: uuid.UUID) -> Category | None: ...

    async def get_by_slug(self, slug: str) -> Category | None: ...

    async def list_all(self, *, published_only: bool = False) -> Sequence[Category]: ...

    async def add(self, category: Category) -> None: ...

    async def update(self, category: Category) -> None: ...


@runtime_checkable
class ProductRepository(Protocol):
    async def get(self, product_id: uuid.UUID) -> Product | None: ...

    async def get_by_slug(self, slug: str) -> Product | None: ...

    async def list_all(
        self,
        *,
        category_id: uuid.UUID | None = None,
        published_only: bool = False,
    ) -> Sequence[Product]: ...

    async def add(self, product: Product) -> None: ...

    async def update(self, product: Product) -> None: ...


@runtime_checkable
class PlanRepository(Protocol):
    async def get(self, plan_id: uuid.UUID) -> Plan | None: ...

    async def get_by_slug(self, slug: str) -> Plan | None: ...

    async def list_for_product(
        self, product_id: uuid.UUID, *, published_only: bool = False
    ) -> Sequence[Plan]: ...

    async def list_all(self, *, published_only: bool = False) -> Sequence[Plan]: ...

    async def add(self, plan: Plan) -> None: ...

    async def update(self, plan: Plan) -> None: ...

    async def has_orders(self, plan_id: uuid.UUID) -> bool:
        """Whether this plan has ever been sold.

        Gate for deletion. A plan referenced by an order must be archived, not
        removed, or historical invoices lose their line items.
        """
        ...


@runtime_checkable
class CouponRepository(Protocol):
    async def get(self, coupon_id: uuid.UUID) -> Coupon | None: ...

    async def get_by_code(self, code: str) -> Coupon | None: ...

    async def list_all(
        self, *, active_only: bool = False, limit: int = 100, offset: int = 0
    ) -> Sequence[Coupon]: ...

    async def add(self, coupon: Coupon) -> None: ...

    async def update(self, coupon: Coupon) -> None: ...

    async def redemption_count_for_user(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int: ...

    async def record_redemption(
        self,
        *,
        coupon_id: uuid.UUID,
        user_id: uuid.UUID,
        order_id: uuid.UUID | None,
        discount: int,
        redeemed_at: datetime,
    ) -> None:
        """Persist one redemption.

        A dedicated table rather than a counter column, because "has this
        customer used this code?" and "who used this code?" are both real
        questions, and because a counter cannot be audited or reversed.
        """
        ...


@runtime_checkable
class CampaignRepository(Protocol):
    async def get(self, campaign_id: uuid.UUID) -> Campaign | None: ...

    async def get_by_slug(self, slug: str) -> Campaign | None: ...

    async def list_all(
        self, *, limit: int = 100, offset: int = 0, include_archived: bool = False
    ) -> Sequence[Campaign]:
        """Archived campaigns are excluded unless asked for.

        Archiving is how a campaign is removed - one referenced by a
        historical order must not be deleted - so it has to disappear from
        the listing, or the archive button looks like it did nothing.
        """
        ...

    async def list_running(self, *, now: datetime) -> Sequence[Campaign]:
        """Every campaign that could apply right now.

        Called on every storefront render, so the implementation filters by
        window and state in SQL rather than loading the table and filtering in
        Python.
        """
        ...

    async def add(self, campaign: Campaign) -> None: ...

    async def update(self, campaign: Campaign) -> None: ...
