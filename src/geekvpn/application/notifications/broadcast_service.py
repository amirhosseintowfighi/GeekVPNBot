"""Admin broadcasts.

Composing, scheduling and sending one Persian message to a computed segment.

Sending is batched rather than one big loop because Telegram's global ceiling
is roughly thirty messages a second: firing five thousand at once earns a 429
and a retry-after, which is slower than pacing. Each batch is committed, so a
crash halfway through loses at most one batch and the broadcast resumes from
its recorded progress instead of starting over and double-messaging everyone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from geekvpn.application.notifications.engine import NotificationEngine
from geekvpn.application.notifications.ports import (
    AudienceResolver,
    BroadcastRepository,
    Clock,
    EventPublisher,
    IdGenerator,
)
from geekvpn.domain.notifications.broadcast import DEFAULT_BATCH_SIZE, Broadcast
from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    DeliveryState,
    NotificationCategory,
)
from geekvpn.domain.notifications.errors import EmptyAudience
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.domain.notifications.schedule import broadcast_dedupe_key


@dataclass(frozen=True, slots=True)
class BroadcastProgress:
    """Result of one send pass over a broadcast."""

    broadcast_id: str
    state: BroadcastState
    sent: int
    suppressed: int
    failed: int
    remaining: int

    @property
    def finished(self) -> bool:
        return self.state.is_terminal()


class BroadcastService:
    """Create, schedule, send and cancel admin broadcasts."""

    def __init__(
        self,
        *,
        engine: NotificationEngine,
        broadcasts: BroadcastRepository,
        audiences: AudienceResolver,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._engine = engine
        self._broadcasts = broadcasts
        self._audiences = audiences
        self._clock = clock
        self._ids = ids
        self._events = events
        self._batch_size = batch_size

    # ---- Composition ----------------------------------------------------

    def create(
        self,
        *,
        title_fa: str,
        body_fa: str,
        audience: AudienceKind,
        created_by: int,
        audience_ref: str | None = None,
        category: NotificationCategory = NotificationCategory.NEWS,
    ) -> Broadcast:
        now = self._clock.now()
        broadcast = Broadcast.draft(
            self._ids.new_id(),
            title_fa=title_fa,
            body_fa=body_fa,
            audience=audience,
            created_by=created_by,
            now=now,
            category=category,
            audience_ref=audience_ref,
        )
        self._broadcasts.save(broadcast)
        return broadcast

    def edit(
        self,
        broadcast_id: str,
        *,
        title_fa: str | None = None,
        body_fa: str | None = None,
        audience: AudienceKind | None = None,
        audience_ref: str | None = None,
    ) -> Broadcast:
        broadcast = self._broadcasts.get(broadcast_id)
        broadcast.edit(
            title_fa=title_fa,
            body_fa=body_fa,
            audience=audience,
            audience_ref=audience_ref,
        )
        self._broadcasts.save(broadcast)
        return broadcast

    def schedule(self, broadcast_id: str, *, send_at: datetime) -> Broadcast:
        broadcast = self._broadcasts.get(broadcast_id)
        broadcast.schedule(send_at=send_at, now=self._clock.now())
        self._broadcasts.save(broadcast)
        self._events.publish_all(broadcast.collect_events())
        return broadcast

    def cancel(self, broadcast_id: str, *, cancelled_by: int) -> Broadcast:
        broadcast = self._broadcasts.get(broadcast_id)
        broadcast.cancel(cancelled_by=cancelled_by, now=self._clock.now())
        self._broadcasts.save(broadcast)
        self._events.publish_all(broadcast.collect_events())
        return broadcast

    def preview(self, broadcast_id: str) -> RenderedMessage:
        """Exactly what a recipient will see, rendered through the catalogue."""
        broadcast = self._broadcasts.get(broadcast_id)
        return self._message_for(broadcast)

    def audience_size(self, broadcast_id: str) -> int:
        broadcast = self._broadcasts.get(broadcast_id)
        return len(self._recipients(broadcast))

    # ---- Sending --------------------------------------------------------

    def send_now(self, broadcast_id: str) -> BroadcastProgress:
        """Resolve the audience and send it all, batch by batch."""
        broadcast = self._broadcasts.get(broadcast_id)
        recipients = self._recipients(broadcast)
        if not recipients:
            raise EmptyAudience(
                "Broadcast audience resolved to nobody.",
                broadcast_id=broadcast_id,
                audience=str(broadcast.audience),
            )

        now = self._clock.now()
        broadcast.start(recipient_count=len(recipients), now=now)
        self._broadcasts.save(broadcast)
        self._events.publish_all(broadcast.collect_events())

        message = self._message_for(broadcast)
        index = 0

        while index < len(recipients):
            batch = recipients[index : index + self._batch_size]
            index += len(batch)

            # Re-read so an operator's cancellation lands between batches.
            broadcast = self._broadcasts.get(broadcast.id)
            if broadcast.state is not BroadcastState.SENDING:
                break

            self._send_batch(broadcast, batch, message)
            self._broadcasts.save(broadcast)

        broadcast = self._broadcasts.get(broadcast.id)
        if broadcast.state is BroadcastState.SENDING:
            broadcast.complete(now=self._clock.now())
            self._broadcasts.save(broadcast)
            self._events.publish_all(broadcast.collect_events())

        return BroadcastProgress(
            broadcast_id=broadcast.id,
            state=broadcast.state,
            sent=broadcast.sent,
            suppressed=broadcast.suppressed,
            failed=broadcast.failed,
            remaining=max(0, broadcast.recipient_count - broadcast.processed()),
        )

    def dispatch_due(self, *, limit: int = 10) -> list[BroadcastProgress]:
        """Run every scheduled broadcast whose time has come.

        One broadcast blowing up must not strand the rest, so failures are
        recorded on the aggregate rather than raised.
        """
        now = self._clock.now()
        results: list[BroadcastProgress] = []

        for broadcast in self._broadcasts.due(now, limit=limit):
            try:
                results.append(self.send_now(broadcast.id))
            except Exception as exc:
                broadcast = self._broadcasts.get(broadcast.id)
                if not broadcast.state.is_terminal():
                    broadcast.fail(error=type(exc).__name__, now=self._clock.now())
                    self._broadcasts.save(broadcast)
                results.append(
                    BroadcastProgress(
                        broadcast_id=broadcast.id,
                        state=broadcast.state,
                        sent=broadcast.sent,
                        suppressed=broadcast.suppressed,
                        failed=broadcast.failed,
                        remaining=0,
                    )
                )

        return results

    # ---- Internals ------------------------------------------------------

    def _recipients(self, broadcast: Broadcast) -> list[int]:
        return self._audiences.resolve(broadcast.audience, reference=broadcast.audience_ref)

    @staticmethod
    def _message_for(broadcast: Broadcast) -> RenderedMessage:
        """Admin copy is passed through, not templated.

        It still becomes a RenderedMessage so broadcasts and system notices
        travel the identical path through the engine.
        """
        return RenderedMessage(
            key="broadcast.custom",
            category=broadcast.category,
            title_fa=broadcast.title_fa,
            body_fa=broadcast.body_fa,
            action=None,
        )

    def _send_batch(self, broadcast: Broadcast, batch: list[int], message: RenderedMessage) -> None:
        sent = suppressed = failed = 0

        for user_id in batch:
            result = self._engine.dispatch(
                user_id=user_id,
                message=message,
                dedupe_key=broadcast_dedupe_key(broadcast.id, user_id),
                source=f"broadcast:{broadcast.id}",
            )
            if not result.was_queued:
                suppressed += 1
            elif result.delivered or result.deferred:
                # A deferred message is not a failure; it goes out at dawn.
                sent += 1
            elif any(state is DeliveryState.FAILED for state in result.outcomes.values()):
                failed += 1
            else:
                suppressed += 1

        broadcast.record_batch(sent=sent, suppressed=suppressed, failed=failed)


__all__ = ["BroadcastProgress", "BroadcastService"]
