"""Free trial claims (see `FreeTrial`).

`claim` is one insert that does nothing on conflict, so the primary key settles
two claims in flight at once and neither transaction is left broken.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.infrastructure.persistence.models.provisioning import FreeTrialClaimModel

_Row = FreeTrialClaimModel


class SqlAlchemyFreeTrialRepository:
    """Implements `FreeTrialRepository` over PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def has_claimed(self, user_id: int) -> bool:
        return await self._db.get(_Row, user_id) is not None

    async def claim(self, user_id: int, *, at: datetime) -> bool:
        stmt = (
            insert(_Row)
            .values(user_id=user_id, claimed_at=at)
            .on_conflict_do_nothing(index_elements=[_Row.user_id])
        )
        result = await self._db.execute(stmt)
        return bool(getattr(result, "rowcount", 0))
