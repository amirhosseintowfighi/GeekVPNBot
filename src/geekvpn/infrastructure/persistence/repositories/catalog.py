"""SQLAlchemy catalog repositories.

Three things these implementations do deliberately:

* **Never commit.** The request's unit of work owns the transaction. A
  repository that commits cannot be composed into a larger operation, which is
  exactly what the order flow will need in Phase 5.
* **Filter in SQL, not in Python.** `list_running` is executed on every
  storefront render. Loading the campaigns table and filtering it in a
  comprehension works fine with four campaigns and becomes the slowest query in
  the system with four hundred.
* **Re-read before write on update.** `update()` fetches the managed row and
  copies the aggregate onto it, rather than merging a detached instance. Merge
  semantics with partially-loaded objects are a reliable source of columns
  quietly reverting to their defaults.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy import true as sa_true
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.category import Category
from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.enums import PublicationState
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.infrastructure.persistence.mappers.catalog import (
    campaign_to_domain,
    campaign_to_row,
    category_to_domain,
    category_to_row,
    coupon_to_domain,
    coupon_to_row,
    plan_to_domain,
    plan_to_row,
    product_to_domain,
    product_to_row,
)
from geekvpn.infrastructure.persistence.models.catalog import (
    CampaignModel,
    CategoryModel,
    CouponModel,
    CouponRedemptionModel,
    PlanModel,
    ProductModel,
)

PUBLISHED = PublicationState.PUBLISHED.value


class SqlAlchemyCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, category_id: uuid.UUID) -> Category | None:
        row = await self._session.get(CategoryModel, category_id)
        return category_to_domain(row) if row else None

    async def get_by_slug(self, slug: str) -> Category | None:
        stmt = select(CategoryModel).where(CategoryModel.slug == slug)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return category_to_domain(row) if row else None

    async def list_all(self, *, published_only: bool = False) -> Sequence[Category]:
        stmt: Select[Any] = select(CategoryModel).order_by(
            CategoryModel.sort_order, CategoryModel.name_fa
        )
        if published_only:
            stmt = stmt.where(CategoryModel.state == PUBLISHED)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [category_to_domain(row) for row in rows]

    async def add(self, category: Category) -> None:
        self._session.add(category_to_row(category))
        await self._session.flush()

    async def update(self, category: Category) -> None:
        row = await self._session.get(CategoryModel, category.id)
        if row is None:
            raise NotFoundError("Category not found.", category_id=str(category.id))
        category_to_row(category, row)
        await self._session.flush()


class SqlAlchemyProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, product_id: uuid.UUID) -> Product | None:
        row = await self._session.get(ProductModel, product_id)
        return product_to_domain(row) if row else None

    async def get_by_slug(self, slug: str) -> Product | None:
        stmt = select(ProductModel).where(ProductModel.slug == slug)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return product_to_domain(row) if row else None

    async def list_all(
        self,
        *,
        category_id: uuid.UUID | None = None,
        published_only: bool = False,
    ) -> Sequence[Product]:
        stmt: Select[Any] = select(ProductModel).order_by(
            ProductModel.sort_order, ProductModel.name_fa
        )
        if category_id is not None:
            stmt = stmt.where(ProductModel.category_id == category_id)
        if published_only:
            stmt = stmt.where(ProductModel.state == PUBLISHED)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [product_to_domain(row) for row in rows]

    async def add(self, product: Product) -> None:
        self._session.add(product_to_row(product))
        await self._session.flush()

    async def update(self, product: Product) -> None:
        row = await self._session.get(ProductModel, product.id)
        if row is None:
            raise NotFoundError("Product not found.", product_id=str(product.id))
        product_to_row(product, row)
        await self._session.flush()


class SqlAlchemyPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, plan_id: uuid.UUID) -> Plan | None:
        row = await self._session.get(PlanModel, plan_id)
        return plan_to_domain(row) if row else None

    async def get_by_slug(self, slug: str) -> Plan | None:
        stmt = select(PlanModel).where(PlanModel.slug == slug)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return plan_to_domain(row) if row else None

    async def list_for_product(
        self, product_id: uuid.UUID, *, published_only: bool = False
    ) -> Sequence[Plan]:
        stmt: Select[Any] = (
            select(PlanModel)
            .where(PlanModel.product_id == product_id)
            .order_by(PlanModel.sort_order, PlanModel.duration_days)
        )
        if published_only:
            stmt = stmt.where(PlanModel.state == PUBLISHED)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [plan_to_domain(row) for row in rows]

    async def list_all(self, *, published_only: bool = False) -> Sequence[Plan]:
        stmt: Select[Any] = select(PlanModel).order_by(
            PlanModel.sort_order, PlanModel.duration_days
        )
        if published_only:
            # Joining to the product means an unpublished product hides its
            # plans automatically. Otherwise archiving a product leaves its
            # packages purchasable via deep link.
            stmt = stmt.join(ProductModel).where(
                and_(PlanModel.state == PUBLISHED, ProductModel.state == PUBLISHED)
            )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [plan_to_domain(row) for row in rows]

    async def add(self, plan: Plan) -> None:
        self._session.add(plan_to_row(plan))
        await self._session.flush()

    async def update(self, plan: Plan) -> None:
        row = await self._session.get(PlanModel, plan.id)
        if row is None:
            raise NotFoundError("Plan not found.", plan_id=str(plan.id))
        plan_to_row(plan, row)
        await self._session.flush()

    async def has_orders(self, plan_id: uuid.UUID) -> bool:
        """Always true until the orders table exists.

        Returning `True` is the safe default: it forces archive-instead-of-
        delete today, and when Phase 5 adds the orders table this becomes a
        real count without any caller changing behaviour in a surprising
        direction.
        """
        return True


class SqlAlchemyCouponRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, coupon_id: uuid.UUID) -> Coupon | None:
        row = await self._session.get(CouponModel, coupon_id)
        return coupon_to_domain(row) if row else None

    async def get_by_code(self, code: str) -> Coupon | None:
        stmt = select(CouponModel).where(CouponModel.code == code)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return coupon_to_domain(row) if row else None

    async def list_all(
        self, *, active_only: bool = False, limit: int = 100, offset: int = 0
    ) -> Sequence[Coupon]:
        stmt: Select[Any] = (
            select(CouponModel).order_by(CouponModel.created_at.desc()).limit(limit).offset(offset)
        )
        if active_only:
            stmt = stmt.where(CouponModel.state == PUBLISHED)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [coupon_to_domain(row) for row in rows]

    async def add(self, coupon: Coupon) -> None:
        self._session.add(coupon_to_row(coupon))
        await self._session.flush()

    async def update(self, coupon: Coupon) -> None:
        row = await self._session.get(CouponModel, coupon.id)
        if row is None:
            raise NotFoundError("Coupon not found.", coupon_id=str(coupon.id))
        coupon_to_row(coupon, row)
        await self._session.flush()

    async def redemption_count_for_user(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(CouponRedemptionModel)
            .where(
                and_(
                    CouponRedemptionModel.coupon_id == coupon_id,
                    CouponRedemptionModel.user_id == user_id,
                )
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def record_redemption(
        self,
        *,
        coupon_id: uuid.UUID,
        user_id: uuid.UUID,
        order_id: uuid.UUID | None,
        discount: int,
        redeemed_at: datetime,
    ) -> None:
        self._session.add(
            CouponRedemptionModel(
                id=uuid.uuid4(),
                coupon_id=coupon_id,
                user_id=user_id,
                order_id=order_id,
                discount=discount,
                redeemed_at=redeemed_at,
            )
        )
        await self._session.flush()


class SqlAlchemyCampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, campaign_id: uuid.UUID) -> Campaign | None:
        row = await self._session.get(CampaignModel, campaign_id)
        return campaign_to_domain(row) if row else None

    async def get_by_slug(self, slug: str) -> Campaign | None:
        stmt = select(CampaignModel).where(CampaignModel.slug == slug)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return campaign_to_domain(row) if row else None

    async def list_all(
        self, *, limit: int = 100, offset: int = 0, include_archived: bool = False
    ) -> Sequence[Campaign]:
        stmt = (
            select(CampaignModel)
            .where(
                # Archiving is how a campaign is removed. If archived rows kept
                # appearing, the button would look like it had done nothing.
                sa_true() if include_archived else CampaignModel.state != "archived"
            )
            .order_by(CampaignModel.priority.desc(), CampaignModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [campaign_to_domain(row) for row in rows]

    async def list_running(self, *, now: datetime) -> Sequence[Campaign]:
        """Published, inside its window, and not sold out.

        The final `is_running` check still happens in the aggregate - this is a
        pre-filter, not a duplicate of the business rule. Pushing it into SQL
        turns "load every campaign ever created" into an index scan on
        `(state, priority, ends_at)`.
        """
        stmt = (
            select(CampaignModel)
            .where(
                CampaignModel.state == PUBLISHED,
                or_(CampaignModel.starts_at.is_(None), CampaignModel.starts_at <= now),
                or_(CampaignModel.ends_at.is_(None), CampaignModel.ends_at > now),
                or_(
                    CampaignModel.max_redemptions.is_(None),
                    CampaignModel.redemption_count < CampaignModel.max_redemptions,
                ),
            )
            .order_by(CampaignModel.priority.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [campaign_to_domain(row) for row in rows]

    async def add(self, campaign: Campaign) -> None:
        self._session.add(campaign_to_row(campaign))
        await self._session.flush()

    async def update(self, campaign: Campaign) -> None:
        row = await self._session.get(CampaignModel, campaign.id)
        if row is None:
            raise NotFoundError("Campaign not found.", campaign_id=str(campaign.id))
        campaign_to_row(campaign, row)
        await self._session.flush()
