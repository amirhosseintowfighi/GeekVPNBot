"""``UsageHistory`` over ``subscription_usage_days``."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.provisioning.usage_history import KEEP_DAYS, DayUsage
from geekvpn.infrastructure.persistence.models.provisioning import SubscriptionUsageDayModel


class SqlUsageHistory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, subscription_id: str, day: date, used_mib: int) -> None:
        await self._session.execute(
            insert(SubscriptionUsageDayModel)
            .values(subscription_id=subscription_id, day=day, used_mib=used_mib)
            .on_conflict_do_update(
                index_elements=[
                    SubscriptionUsageDayModel.subscription_id,
                    SubscriptionUsageDayModel.day,
                ],
                set_={"used_mib": used_mib},
            )
        )
        # Pruned as it goes, per service, so no separate job is needed.
        await self._session.execute(
            delete(SubscriptionUsageDayModel).where(
                SubscriptionUsageDayModel.subscription_id == subscription_id,
                SubscriptionUsageDayModel.day < day - timedelta(days=KEEP_DAYS),
            )
        )

    async def readings(self, subscription_id: str, since: date) -> list[DayUsage]:
        rows = (
            await self._session.execute(
                select(SubscriptionUsageDayModel.day, SubscriptionUsageDayModel.used_mib)
                .where(
                    SubscriptionUsageDayModel.subscription_id == subscription_id,
                    SubscriptionUsageDayModel.day >= since,
                )
                .order_by(SubscriptionUsageDayModel.day)
            )
        ).all()
        return [DayUsage(day=row[0], used_mib=int(row[1])) for row in rows]


__all__ = ["SqlUsageHistory"]
