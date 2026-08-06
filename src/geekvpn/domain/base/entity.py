"""Entities and aggregate roots."""

from __future__ import annotations

from typing import TypeVar

from geekvpn.domain.base.events import DomainEvent

IdT = TypeVar("IdT")


class Entity[IdT]:
    """Identity-based equality. Two entities are the same if their ids match."""

    __slots__ = ("id",)

    def __init__(self, entity_id: IdT) -> None:
        self.id = entity_id

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return self.id == other.id  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.id!r})"


class AggregateRoot(Entity[IdT]):
    """Consistency boundary and the only thing a repository may load or save.

    Aggregates record domain events instead of publishing them. The unit of
    work collects them after a successful commit and hands them to the outbox,
    which is what makes the event bus transactional.
    """

    __slots__ = ("_events",)

    def __init__(self, entity_id: IdT) -> None:
        super().__init__(entity_id)
        self._events: list[DomainEvent] = []

    def record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        """Return and clear the pending events. Called once, by the unit of work."""
        events, self._events = self._events, []
        return events
