"""Rate limiting port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RateLimitVerdict:
    allowed: bool
    remaining: int
    retry_after_seconds: int


@runtime_checkable
class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitVerdict:
        """Count one attempt against `key` and report whether it is allowed."""
        ...

    async def reset(self, key: str) -> None: ...
