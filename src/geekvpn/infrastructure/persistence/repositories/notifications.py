"""Notification repositories: the inbox, preferences, broadcasts, and jobs.

The dedupe lookup is the load-bearing method here. Every reminder job asks
"have I already told this person this?" before sending, and the answer must
come from an index rather than from the job's memory - jobs restart, and a
restart must not re-send yesterday's expiry warning to ten thousand people.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.notifications.broadcast import Broadcast
from geekvpn.domain.notifications.enums import BroadcastState, DeliveryState, JobKind
from geekvpn.domain.notifications.notification import Notification
from geekvpn.domain.notifications.preferences import NotificationPreferences
from geekvpn.domain.notifications.schedule import ScheduleEntry
from geekvpn.infrastructure.persistence.mappers.notifications import (
    broadcast_apply,
    broadcast_to_domain,
    broadcast_to_row,
    notification_apply,
    notification_to_domain,
    notification_to_row,
    preferences_apply,
    preferences_to_domain,
    preferences_to_row,
    schedule_apply,
    schedule_to_domain,
    schedule_to_row,
)
from geekvpn.infrastructure.persistence.models.notifications import (
    BroadcastModel,
    NotificationModel,
    NotificationPreferenceModel,
    ScheduledJobModel,
)

#: Rows the dispatcher may still act on.
_UNSETTLED = (DeliveryState.PENDING.value, DeliveryState.DEFERRED.value)


class SqlAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, notification_id: str) -> Notification | None:
        row = await self._session.get(NotificationModel, notification_id)
        return notification_to_domain(row) if row else None

    async def exists_with_dedupe_key(self, dedupe_key: str) -> bool:
        stmt = (
            select(NotificationModel.id).where(NotificationModel.dedupe_key == dedupe_key).limit(1)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def list_inbox(
        self, user_id: int, *, limit: int = 20, offset: int = 0, unread_only: bool = False
    ) -> Sequence[Notification]:
        stmt: Select[Any] = select(NotificationModel).where(NotificationModel.user_id == user_id)
        if unread_only:
            stmt = stmt.where(NotificationModel.read_at.is_(None))
        stmt = stmt.order_by(NotificationModel.queued_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [notification_to_domain(row) for row in rows]

    async def count_unread(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.read_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_due(self, *, now: datetime, limit: int = 200) -> Sequence[Notification]:
        """Queued or deferred work whose time has come.

        A NULL ``send_after`` means "as soon as possible", so it must be
        included - otherwise every ordinary notification would sit forever
        waiting for a timestamp it never had.
        """
        stmt = (
            select(NotificationModel)
            .where(
                NotificationModel.state.in_(_UNSETTLED),
                or_(
                    NotificationModel.send_after.is_(None),
                    NotificationModel.send_after <= now,
                ),
            )
            .order_by(NotificationModel.queued_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [notification_to_domain(row) for row in rows]

    async def mark_all_read(self, user_id: int, *, now: datetime) -> int:
        """Bulk read receipt, done in SQL.

        Loading every notification to set one timestamp would be thousands of
        objects for a button press that means "I glanced at the list".
        """
        stmt = select(NotificationModel).where(
            NotificationModel.user_id == user_id,
            NotificationModel.read_at.is_(None),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        for row in rows:
            row.read_at = now
        await self._session.flush()
        return len(rows)

    async def add(self, notification: Notification, *, broadcast_id: str | None = None) -> None:
        self._session.add(notification_to_row(notification, broadcast_id=broadcast_id))
        await self._session.flush()

    async def add_many(
        self, notifications: Sequence[Notification], *, broadcast_id: str | None = None
    ) -> None:
        """Bulk insert for broadcasts. One flush, not one per recipient."""
        self._session.add_all(
            [notification_to_row(item, broadcast_id=broadcast_id) for item in notifications]
        )
        await self._session.flush()

    async def update(self, notification: Notification) -> None:
        row = await self._session.get(NotificationModel, notification.id)
        if row is None:
            raise NotFoundError("Notification not found.", notification_id=notification.id)
        notification_apply(row, notification)
        await self._session.flush()


class SqlAlchemyPreferenceRepository:
    """Preferences with a defaulting read.

    Most users never open the settings screen, so most users have no row. The
    repository answers with defaults rather than ``None`` so that no caller can
    forget to handle absence and accidentally treat "unset" as "opted out".
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> NotificationPreferences:
        row = await self._session.get(NotificationPreferenceModel, user_id)
        return preferences_to_domain(row)

    async def save(self, user_id: int, prefs: NotificationPreferences) -> None:
        row = await self._session.get(NotificationPreferenceModel, user_id)
        if row is None:
            self._session.add(preferences_to_row(user_id, prefs))
        else:
            preferences_apply(row, prefs)
        await self._session.flush()


class SqlAlchemyBroadcastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, broadcast_id: str) -> Broadcast | None:
        row = await self._session.get(BroadcastModel, broadcast_id)
        return broadcast_to_domain(row) if row else None

    async def list_recent(
        self, *, limit: int = 25, offset: int = 0, state: BroadcastState | None = None
    ) -> Sequence[Broadcast]:
        stmt: Select[Any] = select(BroadcastModel)
        if state is not None:
            stmt = stmt.where(BroadcastModel.state == state.value)
        stmt = stmt.order_by(BroadcastModel.created_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [broadcast_to_domain(row) for row in rows]

    async def list_due(self, *, now: datetime, limit: int = 10) -> Sequence[Broadcast]:
        """Scheduled broadcasts whose moment has arrived.

        ``SENDING`` rows are included so that a dispatcher killed mid-run picks
        its own work back up instead of leaving half an audience unmessaged.
        """
        stmt = (
            select(BroadcastModel)
            .where(
                or_(
                    (BroadcastModel.state == BroadcastState.SCHEDULED.value)
                    & (BroadcastModel.scheduled_for.is_not(None))
                    & (BroadcastModel.scheduled_for <= now),
                    BroadcastModel.state == BroadcastState.SENDING.value,
                )
            )
            .order_by(BroadcastModel.scheduled_for)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [broadcast_to_domain(row) for row in rows]

    async def add(self, broadcast: Broadcast) -> None:
        self._session.add(broadcast_to_row(broadcast))
        await self._session.flush()

    async def update(self, broadcast: Broadcast) -> None:
        row = await self._session.get(BroadcastModel, broadcast.id)
        if row is None:
            raise NotFoundError("Broadcast not found.", broadcast_id=broadcast.id)
        broadcast_apply(row, broadcast)
        await self._session.flush()


class SqlAlchemyScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job: JobKind) -> ScheduleEntry | None:
        row = await self._session.get(ScheduledJobModel, job.value)
        return schedule_to_domain(row) if row else None

    async def list_all(self) -> Sequence[ScheduleEntry]:
        stmt = select(ScheduledJobModel).order_by(ScheduledJobModel.job)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [schedule_to_domain(row) for row in rows]

    async def save(self, entry: ScheduleEntry) -> None:
        row = await self._session.get(ScheduledJobModel, entry.job.value)
        if row is None:
            self._session.add(schedule_to_row(entry))
        else:
            schedule_apply(row, entry)
        await self._session.flush()

    async def record_run(
        self,
        job: JobKind,
        *,
        ran_at: datetime,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        """Operational bookkeeping the aggregate deliberately does not carry.

        Duration and last error are how an operator sees a job degrading; they
        are not business rules, so they never entered the domain model.
        """
        row = await self._session.get(ScheduledJobModel, job.value)
        if row is None:
            raise NotFoundError("Scheduled job not found.", job=job.value)
        row.last_run_at = ran_at
        row.last_duration_ms = duration_ms
        row.last_error = error
        await self._session.flush()


__all__ = [
    "SqlAlchemyBroadcastRepository",
    "SqlAlchemyNotificationRepository",
    "SqlAlchemyPreferenceRepository",
    "SqlAlchemyScheduleRepository",
]
