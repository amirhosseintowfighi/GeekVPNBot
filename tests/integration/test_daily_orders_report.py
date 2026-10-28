"""The daily orders report's figures, counted by Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from geekvpn.application.analytics.daily_report import bounds
from geekvpn.infrastructure.analytics.daily_orders import SqlDayOrdersReader
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel

pytestmark = pytest.mark.integration

DAY = date(2026, 10, 28)
START, END = bounds(DAY)
NOON = START + timedelta(hours=12)


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


def _order(
    state: str,
    total: int,
    *,
    placed: datetime = NOON,
    paid: datetime | None = NOON,
    renewal: bool = False,
) -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=uuid.uuid4().hex[:12],
        user_id=1,
        state=state,
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa="ماهانه",
        duration_days=30,
        list_price=total,
        total=total,
        is_renewal=renewal,
        placed_at=placed,
        paid_at=paid,
    )


@pytest.fixture
async def session(schema: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().postgres.dsn())
    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        opened.add_all(
            [
                _order("active", 100_000),
                _order("active", 200_000, renewal=True),
                _order("paid", 50_000),
                _order("failed", 70_000),
                _order("pending", 90_000, paid=None),
                _order("cancelled", 90_000, paid=None),
                _order("refunded", 300_000),
                # Placed the day before, paid this day: money of this day,
                # an order of the day before.
                _order("active", 400_000, placed=START - timedelta(hours=2)),
                # The next day entirely.
                _order(
                    "active",
                    999_000,
                    placed=END + timedelta(hours=1),
                    paid=END + timedelta(hours=1),
                ),
                UserModel(
                    id=uuid.uuid4(),
                    telegram_id=10,
                    first_name="a",
                    status="active",
                    referral_code="r10",
                    language="fa",
                    created_at=NOON,
                ),
                UserModel(
                    id=uuid.uuid4(),
                    telegram_id=11,
                    first_name="b",
                    status="active",
                    referral_code="r11",
                    language="fa",
                    created_at=START - timedelta(days=3),
                ),
            ]
        )
        await opened.commit()
        yield opened
    await engine.dispose()


async def test_orders_are_counted_by_what_became_of_them(session: AsyncSession) -> None:
    day = await SqlDayOrdersReader(session).day(DAY, start=START, end=END)

    assert day.placed == 7
    assert (day.delivered, day.waiting, day.failed, day.unpaid, day.refunded) == (2, 1, 1, 2, 1)
    assert day.success_percent == 40  # 2 delivered of 5 paid


async def test_revenue_is_money_kept_that_day(session: AsyncSession) -> None:
    """By payment date, refunds left out: 100 + 200 + 50 + 70 + 400 (paid
    this day for an order of the day before)."""
    day = await SqlDayOrdersReader(session).day(DAY, start=START, end=END)

    assert day.revenue == 820_000
    assert day.renewals == 1


async def test_new_customers_are_those_who_joined_that_day(session: AsyncSession) -> None:
    day = await SqlDayOrdersReader(session).day(DAY, start=START, end=END)

    assert day.new_customers == 1
