"""Outbound domain events.

The production implementation writes to the Postgres outbox table inside the
same transaction as the state change - no dual write, no lost events.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from geekvpn.domain.base.events import DomainEvent


@runtime_checkable
class EventPublisher(Protocol):
    async def publish(self, events: Sequence[DomainEvent]) -> None: ...
