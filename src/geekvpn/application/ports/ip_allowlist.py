"""Network allow-listing port.

The matching itself is address arithmetic and lives in infrastructure; the
application layer only needs to ask "may this address proceed?". Kept as a port
rather than a `frozenset[str]` because exact string equality is not what an
operator means by an allowlist: `10.0.0.0/8` is one entry, not sixteen million.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IpAllowlistPort(Protocol):
    @property
    def is_empty(self) -> bool:
        """Whether nothing is configured, i.e. every address is allowed."""
        ...

    def allows(self, value: str | None) -> bool:
        """Whether this address may proceed. An unparseable address must not."""
        ...
