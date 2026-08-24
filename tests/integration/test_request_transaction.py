"""A successful request must commit. Nothing did.

`get_unit_of_work` opened a transaction, rolled it back on error, and closed it
on success without committing. None of the seven async admin routers called
`commit` either. So every write through that scope - a category, a product, a
coupon, a campaign, a node - answered 201 and changed nothing, and the panel
re-read the list and showed what had always been there.

The failure mode is the dangerous one: the operator is told it worked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geekvpn.presentation.api.dependencies import get_unit_of_work

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rolled_back += 1
        self.closed = True

    async def commit(self) -> None:
        self.committed += 1


def container_yielding(uow: FakeUnitOfWork) -> SimpleNamespace:
    return SimpleNamespace(unit_of_work=lambda: uow)


async def test_a_request_that_succeeds_commits() -> None:
    uow = FakeUnitOfWork()
    generator = get_unit_of_work(container_yielding(uow))  # type: ignore[arg-type]

    await generator.__anext__()
    with pytest.raises(StopAsyncIteration):
        await generator.__anext__()

    assert uow.committed == 1
    assert uow.closed is True


async def test_a_request_that_fails_commits_nothing() -> None:
    """Half a refund written because the second step raised is not recoverable."""
    uow = FakeUnitOfWork()
    generator = get_unit_of_work(container_yielding(uow))  # type: ignore[arg-type]

    await generator.__anext__()
    with pytest.raises(RuntimeError):
        await generator.athrow(RuntimeError("the endpoint raised"))

    assert uow.committed == 0
    assert uow.rolled_back == 1


async def test_the_transaction_is_closed_either_way() -> None:
    uow = FakeUnitOfWork()
    generator = get_unit_of_work(container_yielding(uow))  # type: ignore[arg-type]

    await generator.__anext__()
    with pytest.raises(RuntimeError):
        await generator.athrow(RuntimeError("boom"))

    assert uow.closed is True
