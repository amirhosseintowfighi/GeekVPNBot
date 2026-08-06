"""Time is an injected dependency, never a global call.

Every timestamp in this system is UTC. Jalali conversion happens only in the
presentation layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware, always UTC."""
        ...
