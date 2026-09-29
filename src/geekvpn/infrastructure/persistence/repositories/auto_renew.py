"""The ``auto_renewals`` switches and the worker's view of them."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.provisioning.auto_renew import (
    EXPIRY_WINDOW,
    AutoRenewResult,
    RenewalCandidate,
)
from geekvpn.infrastructure.persistence.models.provisioning import (
    AutoRenewalModel,
    SubscriptionModel,
)


class SqlAutoRenewals:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, subscription_id: str) -> AutoRenewalModel | None:
        return await self._session.get(AutoRenewalModel, subscription_id)

    async def set_enabled(
        self, subscription_id: str, *, telegram_id: int, enabled: bool, now: datetime
    ) -> None:
        await self._session.execute(
            insert(AutoRenewalModel)
            .values(
                subscription_id=subscription_id,
                telegram_id=telegram_id,
                enabled=enabled,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[AutoRenewalModel.subscription_id],
                # A fresh switch-on deserves a fresh attempt, not the old wait.
                set_={
                    "enabled": enabled,
                    "updated_at": now,
                    "telegram_id": telegram_id,
                    "last_attempt_at": None,
                },
            )
        )

    async def candidates(self, now: datetime, *, limit: int = 200) -> list[RenewalCandidate]:
        """Enabled, active platform services; `is_due` makes the final call.

        The traffic rule needs the row either way, so only the expiry side
        narrows the query: anything already past its window is left out.
        """
        rows = (
            await self._session.execute(
                select(AutoRenewalModel, SubscriptionModel)
                .join(SubscriptionModel, SubscriptionModel.id == AutoRenewalModel.subscription_id)
                .where(
                    AutoRenewalModel.enabled.is_(True),
                    SubscriptionModel.state == "active",
                    SubscriptionModel.reseller_id.is_(None),
                    SubscriptionModel.expires_at > now,
                )
                .order_by(SubscriptionModel.expires_at)
                .limit(limit)
            )
        ).all()
        return [
            RenewalCandidate(
                subscription_id=subscription.id,
                telegram_id=renewal.telegram_id,
                plan_id=str(subscription.plan_id) if subscription.plan_id else None,
                expires_at=subscription.expires_at,
                traffic_limit_mib=subscription.traffic_limit_mib,
                traffic_used_mib=subscription.traffic_used_mib,
                last_attempt_at=renewal.last_attempt_at,
            )
            for renewal, subscription in rows
        ]

    async def record(self, subscription_id: str, result: AutoRenewResult, at: datetime) -> None:
        await self._session.execute(
            update(AutoRenewalModel)
            .where(AutoRenewalModel.subscription_id == subscription_id)
            .values(last_attempt_at=at, last_result=result.value)
        )


__all__ = ["EXPIRY_WINDOW", "SqlAutoRenewals"]
