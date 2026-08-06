"""The unit of work must roll back on failure and always close its session."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.unit


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


def _factory(session: _FakeSession):  # type: ignore[no-untyped-def]
    return lambda: session


async def test_commit_path_closes_the_session() -> None:
    session = _FakeSession()
    async with SqlAlchemyUnitOfWork(_factory(session)) as uow:  # type: ignore[arg-type]
        await uow.commit()

    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


async def test_exception_rolls_back_and_closes() -> None:
    session = _FakeSession()
    with pytest.raises(RuntimeError):
        async with SqlAlchemyUnitOfWork(_factory(session)) as uow:  # type: ignore[arg-type]
            assert uow.session is session
            raise RuntimeError("boom")

    assert session.rolled_back is True
    assert session.closed is True


async def test_forgetting_to_commit_does_not_commit() -> None:
    session = _FakeSession()
    async with SqlAlchemyUnitOfWork(_factory(session)):  # type: ignore[arg-type]
        pass

    assert session.committed is False
    assert session.closed is True


def test_session_outside_context_is_a_programming_error() -> None:
    uow = SqlAlchemyUnitOfWork(_factory(_FakeSession()))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="outside of an `async with`"):
        _ = uow.session
