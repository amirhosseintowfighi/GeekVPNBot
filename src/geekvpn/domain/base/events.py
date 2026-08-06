"""Domain events.

Naming convention: ``<context>.<thing>.<past_tense>.v<N>`` - for example
``billing.wallet.credited.v1``. The version is part of the name because an
event, once published, is a public contract.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Base class for everything that goes through the outbox."""

    name: ClassVar[str] = "domain.event.v1"

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def payload(self) -> dict[str, Any]:
        """Serialisable body. Subclasses override with their own fields."""
        return {}
