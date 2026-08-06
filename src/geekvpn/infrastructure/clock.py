"""System clock. The only place in the codebase allowed to read the wall clock."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Concrete implementation of ``application.ports.Clock``."""

    def now(self) -> datetime:
        return datetime.now(UTC)
