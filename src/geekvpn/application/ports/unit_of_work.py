"""Transaction boundary.

One use case equals one unit of work equals one database transaction.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    """Async context manager that rolls back unless ``commit()`` is called.

    Repositories are attached to concrete implementations as they are
    introduced in later phases; the port stays intentionally small.
    """

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
