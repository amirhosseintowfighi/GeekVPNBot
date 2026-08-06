"""Synchronous notification repositories, shaped to the application ports.

Mirrors ``application/notifications/ports.py`` exactly. See
``sync_payments.py`` for why a synchronous family exists alongside the async
one.

House rules: never commit, filter in SQL, re-read before write.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.notifications.broadcast import Broadcast
from geekvpn.domain.notifications.enums import (
    BroadcastState,
    DeliveryState,
    NotificationCategory,
)
from geekvpn.domain.notifications.notification import Notification
from geekvpn.domain.notifications.preferences import NotificationPreferences
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
)
from geekvpn.infrastructure.persistence.models.notifications import (
    BroadcastModel,
    NotificationModel,
    NotificationPreferenceModel,
)

#: What the daily marketing cap counts. Expiry and traffic warnings are
#: service messages the customer asked for by buying something; only these two
#: categories are marketing and therefore rationed.
MARKETING_CATEGORIES = (
    NotificationCategory.PROMOS.value,
    NotificationCategory.NEWS.value,
)

#: A broadcast the dispatcher still owes work to. ``SENDING`` is included on
#: purpose: if the process is killed mid-send, the broadcast must be picked up
#: again rather than stranded forever in a state nothing scans for.
DUE_BROADCAST_STATES = (
    BroadcastState.SCHEDULED.value,
    BroadcastState.SENDING.value,
)


class SyncNotificationRepository:
    """``application.notifications.ports.NotificationRepository``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, notification_id: str) -> Notification:
        row = self._session.get(NotificationModel, notification_id)
        if row is None:
            raise NotFoundError("Notification not found.", notification_id=notification_id)
        return notification_to_domain(row)

    def save(self, notification: Notification) -> None:
        row = self._session.get(NotificationModel, notification.id)
        if row is None:
            self._session.add(notification_to_row(notification))
        else:
            # Carry the existing broadcast link forward. The aggregate does not
            # know which broadcast produced it, so passing the default would
            # quietly orphan every broadcast notification on its first update.
            notification_apply(row, notification, broadcast_id=row.broadcast_id)
        self._session.flush()

    def for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Notification]:
        stmt = select(NotificationModel).where(NotificationModel.user_id == user_id)
        if unread_only:
            stmt = stmt.where(NotificationModel.read_at.is_(None))
        stmt = (
            stmt.order_by(NotificationModel.queued_at.desc(), NotificationModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [notification_to_domain(row) for row in self._session.execute(stmt).scalars().all()]

    def count_unread(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.read_at.is_(None),
            )
        )
        return int(self._session.execute(stmt).scalar_one())

    def dedupe_exists(self, user_id: int, dedupe_key: str) -> bool:
        """Backs the unique index ``uq_notify_user_dedupe``.

        This is the check that stops a retried job from telling the same
        customer three times that their service expires tomorrow.
        """
        stmt = select(
            select(NotificationModel.id)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.dedupe_key == dedupe_key,
            )
            .exists()
        )
        return bool(self._session.execute(stmt).scalar_one())

    def due_deferred(self, now: datetime, *, limit: int = 100) -> list[Notification]:
        """Quiet-hours messages whose hour has finally come."""
        stmt = (
            select(NotificationModel)
            .where(
                NotificationModel.state == DeliveryState.DEFERRED.value,
                NotificationModel.send_after.is_not(None),
                NotificationModel.send_after <= now,
            )
            .order_by(NotificationModel.send_after.asc())
            .limit(limit)
        )
        return [notification_to_domain(row) for row in self._session.execute(stmt).scalars().all()]

    def marketing_count_since(self, user_id: int, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.category.in_(MARKETING_CATEGORIES),
                NotificationModel.queued_at >= since,
            )
        )
        return int(self._session.execute(stmt).scalar_one())


class SyncPreferencesStore:
    """``application.notifications.ports.PreferencesStore``.

    A customer who has never opened the settings screen has no row, and that
    must mean 'the defaults', not 'send them nothing'.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, user_id: int) -> NotificationPreferences:
        row = self._session.get(NotificationPreferenceModel, user_id)
        return preferences_to_domain(row)

    def save(self, user_id: int, preferences: NotificationPreferences) -> None:
        row = self._session.get(NotificationPreferenceModel, user_id)
        if row is None:
            self._session.add(preferences_to_row(user_id, preferences))
        else:
            preferences_apply(row, preferences)
        self._session.flush()


class SyncBroadcastRepository:
    """``application.notifications.ports.BroadcastRepository``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, broadcast_id: str) -> Broadcast:
        row = self._session.get(BroadcastModel, broadcast_id)
        if row is None:
            raise NotFoundError("Broadcast not found.", broadcast_id=broadcast_id)
        return broadcast_to_domain(row)

    def save(self, broadcast: Broadcast) -> None:
        row = self._session.get(BroadcastModel, broadcast.id)
        if row is None:
            self._session.add(broadcast_to_row(broadcast))
        else:
            broadcast_apply(row, broadcast)
        self._session.flush()

    def due(self, now: datetime, *, limit: int = 10) -> list[Broadcast]:
        stmt = (
            select(BroadcastModel)
            .where(
                BroadcastModel.state.in_(DUE_BROADCAST_STATES),
                BroadcastModel.scheduled_for.is_not(None),
                BroadcastModel.scheduled_for <= now,
            )
            .order_by(BroadcastModel.scheduled_for.asc())
            .limit(limit)
        )
        return [broadcast_to_domain(row) for row in self._session.execute(stmt).scalars().all()]

    def listing(
        self,
        *,
        state: BroadcastState | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Broadcast]:
        stmt = select(BroadcastModel)
        if state is not None:
            stmt = stmt.where(BroadcastModel.state == state.value)
        stmt = (
            stmt.order_by(
                BroadcastModel.scheduled_for.desc().nullsfirst(), BroadcastModel.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return [broadcast_to_domain(row) for row in self._session.execute(stmt).scalars().all()]


__all__ = [
    "DUE_BROADCAST_STATES",
    "MARKETING_CATEGORIES",
    "SyncBroadcastRepository",
    "SyncNotificationRepository",
    "SyncPreferencesStore",
]
