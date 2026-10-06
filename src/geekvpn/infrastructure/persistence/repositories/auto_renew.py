"""The Android app's view of auto-renew: the last attempt and how it went.

The switch itself is `subscriptions.auto_renew`, shared with the bot. This
table keeps what the app shows beside it - when the worker last tried and
what came of it - and mirrors the switch for rows the app wrote before the
two were joined.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.provisioning.auto_renew import AutoRenewResult
from geekvpn.infrastructure.persistence.models.provisioning import AutoRenewalModel


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
                # A fresh switch-on deserves a fresh start, not the old result.
                set_={
                    "enabled": enabled,
                    "updated_at": now,
                    "telegram_id": telegram_id,
                    "last_attempt_at": None,
                    "last_result": None,
                },
            )
        )

    async def record(
        self, subscription_id: str, *, telegram_id: int, result: AutoRenewResult, at: datetime
    ) -> None:
        """Upserted: a switch turned on from the bot has no row until now."""
        await self._session.execute(
            insert(AutoRenewalModel)
            .values(
                subscription_id=subscription_id,
                telegram_id=telegram_id,
                enabled=True,
                updated_at=at,
                last_attempt_at=at,
                last_result=result.value,
            )
            .on_conflict_do_update(
                index_elements=[AutoRenewalModel.subscription_id],
                set_={"last_attempt_at": at, "last_result": result.value},
            )
        )


__all__ = ["SqlAutoRenewals"]
