"""The admin orders page's one search box.

It says "order number or user" and sent only `number`, matched exactly: a
partial number or a customer's Telegram id found nothing. The same page
crashed outright on a cancelled order (`admin/tests/order-states.test.ts`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SqlAlchemyOrderRepository,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def schema() -> Iterator[None]:
    engine = create_engine(
        get_settings().postgres.dsn(driver="postgresql+psycopg"), pool_pre_ping=True
    )
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture
async def session(schema: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().postgres.dsn())
    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        opened.add_all(
            [
                _order("1405-0001", user=555_000_111, minutes=1),
                _order("1405-0002", user=777_000_222, minutes=2),
                _order("1405-0310", user=555_000_111, minutes=3, state="cancelled"),
            ]
        )
        await opened.commit()
        yield opened
    await engine.dispose()


def _order(number: str, *, user: int, minutes: int, state: str = "active") -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=number,
        user_id=user,
        state=state,
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa="ماهانه",
        duration_days=30,
        list_price=100_000,
        total=100_000,
        placed_at=NOW - timedelta(minutes=minutes),
    )


async def test_part_of_an_order_number_finds_it(session: AsyncSession) -> None:
    orders, total = await SqlAlchemyOrderRepository(session).search(query="0002")

    assert [o.number for o in orders] == ["1405-0002"]
    assert total == 1


async def test_a_telegram_id_finds_that_customers_orders(session: AsyncSession) -> None:
    orders, total = await SqlAlchemyOrderRepository(session).search(query="555000111")

    assert {o.number for o in orders} == {"1405-0001", "1405-0310"}
    assert total == 2


async def test_the_search_narrows_a_state_filter_rather_than_replacing_it(
    session: AsyncSession,
) -> None:
    orders, _ = await SqlAlchemyOrderRepository(session).search(
        query="555000111", state=OrderState.CANCELLED
    )

    assert [o.number for o in orders] == ["1405-0310"]


async def test_a_percent_sign_is_searched_for_not_treated_as_a_wildcard(
    session: AsyncSession,
) -> None:
    orders, total = await SqlAlchemyOrderRepository(session).search(query="%")

    assert orders == []
    assert total == 0
