"""Mini App notification inbox.

The read side of the engine. Everything the customer was sent -- including
what Telegram refused to deliver because they blocked the bot -- is listed
here, which is the point of writing the inbox row unconditionally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from geekvpn.application.notifications.ports import (
    Clock,
    EventPublisher,
    NotificationRepository,
)
from geekvpn.domain.notifications.notification import Notification

PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class InboxItem:
    """One row in the Mini App inbox, already Persian and already formatted."""

    notification_id: str
    title_fa: str
    preview_fa: str
    body_fa: str
    category_fa: str
    action: str | None
    created_at: datetime
    unread: bool

    @classmethod
    def of(cls, notification: Notification) -> InboxItem:
        message = notification.message
        return cls(
            notification_id=notification.id,
            title_fa=message.title_fa,
            preview_fa=message.preview(),
            body_fa=message.body_fa,
            category_fa=message.category.label_fa(),
            action=message.action,
            created_at=notification.created_at,
            unread=notification.is_unread(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.notification_id,
            "title_fa": self.title_fa,
            "preview_fa": self.preview_fa,
            "body_fa": self.body_fa,
            "category_fa": self.category_fa,
            "action": self.action,
            "created_at": self.created_at.isoformat(),
            "unread": self.unread,
        }


@dataclass(frozen=True, slots=True)
class InboxPage:
    items: tuple[InboxItem, ...]
    unread_count: int
    has_more: bool


class InboxService:
    """List, count and mark-as-read for the Mini App."""

    def __init__(
        self,
        *,
        notifications: NotificationRepository,
        clock: Clock,
        events: EventPublisher,
    ) -> None:
        self._notifications = notifications
        self._clock = clock
        self._events = events

    def list_for(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> InboxPage:
        """One extra row is fetched to answer ``has_more`` without a count."""
        page = max(1, page)
        offset = (page - 1) * page_size
        rows = self._notifications.for_user(
            user_id,
            unread_only=unread_only,
            limit=page_size + 1,
            offset=offset,
        )
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        return InboxPage(
            items=tuple(InboxItem.of(row) for row in visible),
            unread_count=self._notifications.count_unread(user_id),
            has_more=has_more,
        )

    def unread_count(self, user_id: int) -> int:
        return self._notifications.count_unread(user_id)

    def mark_read(self, notification_id: str, *, user_id: int) -> bool:
        """Mark one item read. Returns False if it was already read.

        Ownership is checked rather than assumed: notification ids are opaque
        but guessable, and one customer must not be able to read another's
        inbox by id.
        """
        notification = self._notifications.get(notification_id)
        if notification.user_id != user_id:
            return False
        changed = notification.mark_read(now=self._clock.now())
        if changed:
            self._notifications.save(notification)
            self._events.publish_all(notification.collect_events())
        return changed

    def mark_all_read(self, user_id: int, *, limit: int = 200) -> int:
        """Bulk read for the \u0647\u0645\u0647 \u062e\u0648\u0627\u0646\u062f\u0647 \u0634\u062f button. Returns how many changed."""
        now = self._clock.now()
        changed = 0
        for notification in self._notifications.for_user(
            user_id, unread_only=True, limit=limit, offset=0
        ):
            if notification.mark_read(now=now):
                self._notifications.save(notification)
                self._events.publish_all(notification.collect_events())
                changed += 1
        return changed


__all__ = ["PAGE_SIZE", "InboxItem", "InboxPage", "InboxService"]
