"""The Broadcast aggregate.

An admin writes one Persian message and sends it to a computed audience. The
interesting part is not the sending, it is the *state machine*: once the first
batch has gone out the copy is frozen, because half the audience already has
the old text and changing it would mean two different messages went out under
one name.

Cancellation mid-send is supported and honest: the aggregate remembers how
many people were already reached before the stop.
"""

from __future__ import annotations

from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    NotificationCategory,
)
from geekvpn.domain.notifications.errors import (
    BroadcastNotEditable,
    IllegalBroadcastTransition,
    NotificationError,
)
from geekvpn.domain.notifications.events import (
    BroadcastCancelled,
    BroadcastCompleted,
    BroadcastScheduled,
    BroadcastStarted,
)

# Mirrors the admin panel's client-side validation so the two cannot drift.
MIN_TITLE = 3
MIN_BODY = 10
MAX_BODY = 4000

# Telegram's global ceiling is about 30 messages/second. Batches are paced by
# the dispatcher; this is the size it asks for at a time.
DEFAULT_BATCH_SIZE = 25


class Broadcast(AggregateRoot[str]):
    """An admin-authored message aimed at a segment of the user base."""

    __slots__ = (
        "audience",
        "audience_ref",
        "body_fa",
        "category",
        "created_at",
        "created_by",
        "error",
        "failed",
        "finished_at",
        "recipient_count",
        "send_at",
        "sent",
        "started_at",
        "state",
        "suppressed",
        "title_fa",
    )

    def __init__(
        self,
        broadcast_id: str,
        *,
        title_fa: str,
        body_fa: str,
        audience: AudienceKind,
        created_by: int,
        created_at: datetime,
        category: NotificationCategory = NotificationCategory.NEWS,
        audience_ref: str | None = None,
    ) -> None:
        super().__init__(broadcast_id)
        self.title_fa = title_fa
        self.body_fa = body_fa
        self.audience = audience
        self.audience_ref = audience_ref
        self.category = category
        self.state = BroadcastState.DRAFT
        self.created_by = created_by
        self.created_at = created_at
        self.send_at: datetime | None = None
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.recipient_count = 0
        self.sent = 0
        self.suppressed = 0
        self.failed = 0
        self.error = ""

    # ---- Construction ---------------------------------------------------

    @staticmethod
    def _validate(title_fa: str, body_fa: str) -> tuple[str, str]:
        title = title_fa.strip()
        body = body_fa.strip()
        if len(title) < MIN_TITLE:
            raise NotificationError(
                f"Broadcast title must be at least {MIN_TITLE} characters.",
                min_title=MIN_TITLE,
            )
        if len(body) < MIN_BODY:
            raise NotificationError(
                f"Broadcast body must be at least {MIN_BODY} characters.",
                min_body=MIN_BODY,
            )
        if len(body) > MAX_BODY:
            raise NotificationError(
                f"Broadcast body must be at most {MAX_BODY} characters.",
                max_body=MAX_BODY,
            )
        return title, body

    @classmethod
    def draft(
        cls,
        broadcast_id: str,
        *,
        title_fa: str,
        body_fa: str,
        audience: AudienceKind,
        created_by: int,
        now: datetime,
        category: NotificationCategory = NotificationCategory.NEWS,
        audience_ref: str | None = None,
    ) -> Broadcast:
        title, body = cls._validate(title_fa, body_fa)
        return cls(
            broadcast_id,
            title_fa=title,
            body_fa=body,
            audience=audience,
            created_by=created_by,
            created_at=now,
            category=category,
            audience_ref=audience_ref,
        )

    @classmethod
    def restore(
        cls,
        broadcast_id: str,
        *,
        title_fa: str,
        body_fa: str,
        audience: AudienceKind,
        created_by: int,
        created_at: datetime,
        state: BroadcastState,
        category: NotificationCategory = NotificationCategory.NEWS,
        audience_ref: str | None = None,
        send_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        recipient_count: int = 0,
        sent: int = 0,
        suppressed: int = 0,
        failed: int = 0,
        error: str = "",
    ) -> Broadcast:
        """Rebuild a broadcast from storage without re-validating or emitting.

        Validation is deliberately skipped: a broadcast that was accepted by an
        older rule set must still be loadable, otherwise a tightened minimum
        length would make historical rows unreadable.
        """
        broadcast = cls(
            broadcast_id,
            title_fa=title_fa,
            body_fa=body_fa,
            audience=audience,
            created_by=created_by,
            created_at=created_at,
            category=category,
            audience_ref=audience_ref,
        )
        broadcast.state = state
        broadcast.send_at = send_at
        broadcast.started_at = started_at
        broadcast.finished_at = finished_at
        broadcast.recipient_count = recipient_count
        broadcast.sent = sent
        broadcast.suppressed = suppressed
        broadcast.failed = failed
        broadcast.error = error
        return broadcast

    # ---- Editing --------------------------------------------------------

    def edit(
        self,
        *,
        title_fa: str | None = None,
        body_fa: str | None = None,
        audience: AudienceKind | None = None,
        audience_ref: str | None = None,
    ) -> None:
        if not self.state.is_editable():
            raise BroadcastNotEditable(broadcast_id=self.id, state=str(self.state))
        title, body = self._validate(
            self.title_fa if title_fa is None else title_fa,
            self.body_fa if body_fa is None else body_fa,
        )
        self.title_fa = title
        self.body_fa = body
        if audience is not None:
            self.audience = audience
            self.audience_ref = audience_ref

    # ---- Lifecycle ------------------------------------------------------

    def schedule(self, *, send_at: datetime, now: datetime) -> None:
        if not self.state.is_editable():
            raise IllegalBroadcastTransition(
                current=str(self.state), target=str(BroadcastState.SCHEDULED)
            )
        if send_at < now:
            raise NotificationError(
                "Broadcast send time cannot be in the past.",
                send_at=send_at.isoformat(),
            )
        self.send_at = send_at
        self.state = BroadcastState.SCHEDULED
        self.record(
            BroadcastScheduled(
                broadcast_id=self.id,
                title_fa=self.title_fa,
                send_at=send_at,
                audience=str(self.audience),
            )
        )

    def is_due(self, now: datetime) -> bool:
        """A draft is never due; only an explicitly scheduled broadcast is."""
        if self.state is not BroadcastState.SCHEDULED:
            return False
        return self.send_at is not None and self.send_at <= now

    def start(self, *, recipient_count: int, now: datetime) -> None:
        if self.state not in (BroadcastState.DRAFT, BroadcastState.SCHEDULED):
            raise IllegalBroadcastTransition(
                current=str(self.state), target=str(BroadcastState.SENDING)
            )
        self.state = BroadcastState.SENDING
        self.recipient_count = recipient_count
        self.started_at = now
        self.record(BroadcastStarted(broadcast_id=self.id, recipient_count=recipient_count))

    def record_batch(self, *, sent: int = 0, suppressed: int = 0, failed: int = 0) -> None:
        """Accumulate one batch's outcome. Safe to call after cancellation.

        A cancelled broadcast can still receive the results of the batch that
        was already in flight; those people really were contacted, so the
        counters must reflect it.
        """
        if self.state not in (BroadcastState.SENDING, BroadcastState.CANCELLED):
            raise IllegalBroadcastTransition(current=str(self.state), target="batch_result")
        self.sent += sent
        self.suppressed += suppressed
        self.failed += failed

    def processed(self) -> int:
        return self.sent + self.suppressed + self.failed

    def progress_percent(self) -> int:
        if self.recipient_count <= 0:
            return 100 if self.state.is_terminal() else 0
        return min(100, int(self.processed() * 100 / self.recipient_count))

    def complete(self, *, now: datetime) -> None:
        if self.state is not BroadcastState.SENDING:
            raise IllegalBroadcastTransition(
                current=str(self.state), target=str(BroadcastState.SENT)
            )
        self.state = BroadcastState.SENT
        self.finished_at = now
        self.record(
            BroadcastCompleted(
                broadcast_id=self.id,
                sent=self.sent,
                suppressed=self.suppressed,
                failed=self.failed,
            )
        )

    def cancel(self, *, cancelled_by: int, now: datetime) -> None:
        """Stop a draft, a schedule, or a send already in progress."""
        if self.state.is_terminal():
            raise IllegalBroadcastTransition(
                current=str(self.state), target=str(BroadcastState.CANCELLED)
            )
        self.state = BroadcastState.CANCELLED
        self.finished_at = now
        self.record(
            BroadcastCancelled(
                broadcast_id=self.id,
                cancelled_by=cancelled_by,
                sent_before_cancel=self.sent,
            )
        )

    def fail(self, *, error: str, now: datetime) -> None:
        if self.state.is_terminal():
            raise IllegalBroadcastTransition(
                current=str(self.state), target=str(BroadcastState.FAILED)
            )
        self.state = BroadcastState.FAILED
        self.error = error
        self.finished_at = now


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "MAX_BODY",
    "MIN_BODY",
    "MIN_TITLE",
    "Broadcast",
]
