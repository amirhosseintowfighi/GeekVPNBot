"""List prices, for callers that need a number and nothing else.

`PlanPrices` exists so reseller pricing does not have to go through the
storefront read model. A reseller's price is the list price minus their
percentage - campaigns, coupons and flash sales are offers made to customers,
and applying them on top of a wholesale discount would sell below cost.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.catalog.money import Money
from geekvpn.infrastructure.persistence.models.catalog import PlanModel


class SqlAlchemyPlanPrices:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_price(self, plan_id: uuid.UUID) -> Money | None:
        row = await self._session.get(PlanModel, plan_id)
        return Money(row.base_price) if row else None


__all__ = ["SqlAlchemyPlanPrices"]
