"""A reseller's charts: their rows only, and totals that keep counting."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from geekvpn.domain.analytics.timeframe import DateRange
from geekvpn.infrastructure.analytics.reseller_trade import SqlResellerTradeReader
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import AdminModel, UserModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel, SubscriptionModel
from geekvpn.infrastructure.persistence.models.resellers import ResellerLedgerModel, ResellerModel

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
MINE, OTHER = uuid.uuid4(), uuid.uuid4()


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
    with Session(engine) as db:
        for shop in (MINE, OTHER):
            admin = AdminModel(
                id=uuid.uuid4(),
                username=f"a{shop.hex[:6]}",
                password_hash="x",
                role="reseller",
                status="active",
            )
            db.add(admin)
            db.flush()
            db.add(ResellerModel(id=shop, admin_id=admin.id, name_fa="شاپ"))
        db.flush()
        # 600 sales: more than the 500 rows the old summary ever read.
        for n in range(600):
            db.add(_ledger(MINE, "sale", -10_000, NOW - timedelta(days=200, minutes=n)))
        db.add(_ledger(MINE, "topup", 5_000_000, NOW - timedelta(days=300)))
        db.add(_ledger(MINE, "sale", -50_000, NOW - timedelta(days=1)))
        db.add(_ledger(MINE, "sale", -50_000, NOW - timedelta(days=1, hours=1)))
        db.add(_ledger(OTHER, "sale", -999_000, NOW - timedelta(days=1)))
        db.add(_order(MINE, "۲۰ گیگ", 80_000))
        db.add(_order(MINE, "۲۰ گیگ", 80_000))
        db.add(_order(MINE, "۵۰ گیگ", 150_000))
        db.add(_order(OTHER, "۱۰۰ گیگ", 900_000))
        db.add(_user(MINE, 1, NOW - timedelta(days=2)))
        db.add(_user(MINE, 2, NOW - timedelta(days=90)))
        db.add(_user(OTHER, 3, NOW - timedelta(days=2)))
        db.add(_subscription(MINE, "s1", "active"))
        db.add(_subscription(MINE, "s2", "expired"))
        db.add(_subscription(OTHER, "s3", "active"))
        db.commit()
    yield
    engine.dispose()


def _ledger(shop: uuid.UUID, kind: str, amount: int, at: datetime) -> ResellerLedgerModel:
    return ResellerLedgerModel(
        id=uuid.uuid4().hex,
        reseller_id=shop,
        amount=amount,
        balance_after=0,
        kind=kind,
        description_fa="",
        occurred_at=at,
    )


def _order(shop: uuid.UUID, plan: str, total: int) -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=uuid.uuid4().hex[:12],
        user_id=1,
        reseller_id=shop,
        state="active",
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa=plan,
        duration_days=30,
        list_price=total,
        total=total,
        placed_at=NOW - timedelta(days=1),
        paid_at=NOW - timedelta(days=1),
    )


def _user(shop: uuid.UUID, telegram_id: int, joined: datetime) -> UserModel:
    return UserModel(
        id=uuid.uuid4(),
        telegram_id=telegram_id,
        reseller_id=shop,
        status="active",
        referral_code=f"r{telegram_id}",
        language="fa",
        created_at=joined,
    )


def _subscription(shop: uuid.UUID, sid: str, state: str) -> SubscriptionModel:
    return SubscriptionModel(
        id=sid,
        user_id=1,
        reseller_id=shop,
        state=state,
        remote_username=sid,
        started_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=29),
        traffic_used_mib=0,
        device_limit=1,
        notified_expiry_days=[],
        notified_traffic_percents=[],
    )


@pytest.fixture
async def session(schema: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().postgres.dsn())
    async with async_sessionmaker(engine, expire_on_commit=False)() as opened:
        yield opened
    await engine.dispose()


async def test_the_charts_hold_this_resellers_rows_and_no_one_elses(session: AsyncSession) -> None:
    trade = await SqlResellerTradeReader(session).trade(MINE, DateRange.calendar_days(30, now=NOW))

    assert trade.sales.total() == 2
    assert trade.cost.total() == 100_000
    assert trade.revenue.total() == 310_000
    assert [(plan.label_fa, plan.value) for plan in trade.top_plans] == [
        ("۲۰ گیگ", 2.0),
        ("۵۰ گیگ", 1.0),
    ]
    assert (trade.new_customers, trade.customers, trade.active_services) == (1, 2, 1)


async def test_totals_count_past_the_five_hundredth_sale(session: AsyncSession) -> None:
    totals = await SqlResellerTradeReader(session).totals(MINE)

    assert totals.sales == 602
    assert totals.spent == 600 * 10_000 + 100_000
    assert totals.topped_up == 5_000_000
    assert totals.average_sale == totals.spent // 602
