"""A reseller's balance moves one change at a time.

Every balance move - a sale, a refund, a top-up, an operator's correction -
read the reseller, changed the number in memory and wrote the whole row back.
Two of them at once both read the same balance and the second write erased the
first: two sales took the price of one, or a top-up vanished under a sale that
finished a moment later. Any other edit to the reseller (a rename, a panel
list) wrote the balance it had read too, and erased whatever sale had happened
in between.

Every change now loads the reseller with the row lock; the second waits for
the first to commit and starts from the balance it left.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.repositories.resellers import (
    SqlAlchemyResellerRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(get_settings().postgres.dsn(driver="postgresql+asyncpg"))
    try:
        async with engine.connect() as probe:
            await probe.execute(text("SELECT 1 FROM resellers LIMIT 0"))
    except (OperationalError, OSError) as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")
    except Exception as exc:  # no schema
        pytest.skip(f"no reseller tables: {exc.__class__.__name__}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def reseller_id(engine: AsyncEngine) -> AsyncIterator[uuid.UUID]:
    admin, reseller = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as cx:
        await cx.execute(
            text(
                "INSERT INTO admins (id, username, password_hash, role, status, "
                "granted_permissions, denied_permissions, is_totp_enabled, failed_attempts) "
                "VALUES (:a, :u, 'x', 'reseller', 'active', '{}', '{}', false, 0)"
            ),
            {"a": admin, "u": f"lock-{admin.hex[:12]}"},
        )
        await cx.execute(
            text("INSERT INTO resellers (id, admin_id, name_fa) VALUES (:r, :a, 'قفل')"),
            {"r": reseller, "a": admin},
        )
    yield reseller
    async with engine.begin() as cx:
        await cx.execute(text("DELETE FROM resellers WHERE id = :r"), {"r": reseller})
        await cx.execute(text("DELETE FROM admins WHERE id = :a"), {"a": admin})


async def test_a_second_change_waits_while_the_first_holds_the_reseller(
    engine: AsyncEngine, reseller_id: uuid.UUID
) -> None:
    async with AsyncSession(engine) as first, AsyncSession(engine) as second:
        assert await SqlAlchemyResellerRepository(first).get_for_update(reseller_id)

        await second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            await SqlAlchemyResellerRepository(second).get_for_update(reseller_id)

        await first.rollback()
        await second.rollback()


async def test_the_second_change_starts_from_the_balance_the_first_left(
    engine: AsyncEngine, reseller_id: uuid.UUID
) -> None:
    async with AsyncSession(engine) as first, AsyncSession(engine) as second:
        # The second session has already read the reseller once, before the
        # first committed: what it holds in memory is the stale balance.
        repo_two = SqlAlchemyResellerRepository(second)
        stale = await repo_two.get(reseller_id)
        assert stale is not None and stale.balance_amount == 0

        repo_one = SqlAlchemyResellerRepository(first)
        held = await repo_one.get_for_update(reseller_id)
        assert held is not None
        held.settle(500_000)
        await repo_one.save(held)
        await first.commit()

        fresh = await repo_two.get_for_update(reseller_id)
        assert fresh is not None and fresh.balance_amount == 500_000
        await second.rollback()
