"""Key-value cache / lock primitives.

Deliberately narrower than the Redis client so the application never depends
on Redis-specific behaviour.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def add_if_absent(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        """Atomic SETNX. Returns True when the key was created by this caller."""
        ...
