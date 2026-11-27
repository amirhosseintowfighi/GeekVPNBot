"""The panel's revenue figures, against a real database.

`infrastructure/analytics/sql_readers.py` had no test that ran its SQL, and its
numbers disagreed with the nightly orders report for the same day:

- a free trial is an order marked paid with a total of zero, and it counted as
  an order and as a paying customer;
- a paid order whose panel refused the service still holds the customer's
  money, and the nightly report counts it while the panel did not;
- a refund for an unused service goes straight to the wallet without a row in
  `refunds`, so net revenue kept the money that was given back;
- days were cut at midnight UTC, 03:30 in Tehran, so a sale at 01:00 Tehran
  time landed on the day before.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.domain.analytics.timeframe import DateRange, Granularity
from geekvpn.infrastructure.analytics.sql_readers import SqlRevenueReader, SqlWorkQueueReader
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.payments import RefundModel, WalletEntryModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel, SubscriptionModel

pytestmark = pytest.mark.integration

TEHRAN = timezone(timedelta(hours=3, minutes=30))
#: 12:00 on 1405/9/6 in Tehran.
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=TEHRAN)


@pytest.fixture
def db() -> Iterator[Session]:
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
    with Session(engine) as session:
        yield session
    engine.dispose()


def _order(
    total: int,
    *,
    paid_at: datetime,
    state: str = "active",
    source: str = "bot",
    user_id: int = 1,
) -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=uuid.uuid4().hex[:12],
        user_id=user_id,
        state=state,
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa="ماهانه",
        duration_days=30,
        list_price=total,
        total=total,
        placed_at=paid_at,
        paid_at=paid_at,
        source=source,
    )


def _wallet_refund(amount: int, *, at: datetime, reference: str) -> WalletEntryModel:
    return WalletEntryModel(
        id=uuid.uuid4().hex,
        user_id=1,
        kind="refund",
        amount=amount,
        balance_after=amount,
        occurred_at=at,
        description_fa="برگشت وجه",
        reference=reference,
    )


def _today() -> DateRange:
    return DateRange.calendar_days(1, now=NOW)


def test_a_free_trial_is_neither_an_order_nor_a_paying_customer(db: Session) -> None:
    db.add(_order(200_000, paid_at=NOW - timedelta(hours=1), user_id=1))
    db.add(_order(0, paid_at=NOW - timedelta(hours=1), source="trial", user_id=2))
    db.commit()

    totals = SqlRevenueReader(db).totals(_today())

    assert (totals.orders, totals.paying_users, totals.gross) == (1, 1, 200_000)


def test_a_paid_order_the_panel_refused_still_holds_the_money(db: Session) -> None:
    """As the nightly report counts it: paid, owed a service, not refunded."""
    db.add(_order(150_000, paid_at=NOW - timedelta(hours=1), state="failed"))
    db.commit()

    totals = SqlRevenueReader(db).totals(_today())

    assert (totals.orders, totals.gross) == (1, 150_000)


def test_a_refund_of_an_unused_service_comes_off_net_revenue(db: Session) -> None:
    order = _order(300_000, paid_at=NOW - timedelta(hours=2), state="refunded")
    db.add(order)
    db.add(_wallet_refund(300_000, at=NOW - timedelta(hours=1), reference=order.number))
    db.commit()

    reader = SqlRevenueReader(db)
    totals = reader.totals(_today())

    assert (totals.gross, totals.refunds, totals.net) == (300_000, 300_000, 0)
    assert sum(reader.net_revenue_by_bucket(_today()).values()) == 0


def test_a_payment_refund_to_the_wallet_is_subtracted_once(db: Session) -> None:
    """It writes a `refunds` row and a wallet credit; only one may count."""
    order = _order(100_000, paid_at=NOW - timedelta(hours=3), state="refunded")
    db.add(order)
    # The refund row alone: what is being pinned is that it and its wallet
    # credit count once, not the payment and invoice it belongs to.
    db.execute(text("SET session_replication_role = replica"))
    db.add(
        RefundModel(
            id="ref-1",
            payment_id="pay-1",
            user_id=1,
            amount=100_000,
            reason="customer_request",
            destination="wallet",
            refunded_at=NOW - timedelta(hours=1),
        )
    )
    db.add(_wallet_refund(100_000, at=NOW - timedelta(hours=1), reference="ref-1"))
    db.commit()

    totals = SqlRevenueReader(db).totals(_today())

    assert totals.refunds == 100_000


def test_a_sale_after_midnight_in_tehran_belongs_to_that_day(db: Session) -> None:
    """01:00 on the 6th in Tehran is 21:30 on the 5th in UTC."""
    early = datetime(2026, 11, 27, 1, 0, tzinfo=TEHRAN)
    db.add(_order(120_000, paid_at=early))
    db.add(_order(80_000, paid_at=early - timedelta(hours=2)))  # 23:00 the day before
    db.commit()

    reader = SqlRevenueReader(db)
    today = reader.totals(_today())
    by_day = reader.net_revenue_by_bucket(DateRange.calendar_days(2, now=NOW))

    assert today.gross == 120_000
    assert list(by_day.values()) == [80_000, 120_000]
    assert [bucket.astimezone(TEHRAN).hour for bucket in by_day] == [0, 0]


def test_weeks_still_start_on_saturday_in_tehran(db: Session) -> None:
    week = DateRange.calendar_days(21, now=NOW).buckets(Granularity.WEEK)

    assert {bucket.astimezone(TEHRAN).weekday() for bucket in week} == {5}
    assert {bucket.astimezone(TEHRAN).hour for bucket in week} == {0}


def test_active_subscriptions_are_counted_not_expiring_ones(db: Session) -> None:
    """The dashboard's card said "active subscriptions" and showed the
    number expiring today."""
    for n, (state, expires) in enumerate(
        [
            ("active", NOW + timedelta(days=20)),
            ("active", NOW + timedelta(days=3)),
            ("active", NOW + timedelta(hours=5)),
            ("expired", NOW - timedelta(days=1)),
        ]
    ):
        db.add(
            SubscriptionModel(
                id=f"s{n}",
                user_id=1,
                state=state,
                remote_username=f"s{n}",
                started_at=NOW - timedelta(days=10),
                expires_at=expires,
                traffic_used_mib=0,
                device_limit=1,
                notified_expiry_days=[],
                notified_traffic_percents=[],
            )
        )
    db.commit()

    queue = SqlWorkQueueReader(db).pending(now=NOW.astimezone(UTC))

    assert queue.active_subscriptions == 3
    assert queue.expiring_today == 1


# -- the bot's «آمار امروز» --------------------------------------------------------


async def test_todays_stats_in_the_bot_are_the_nightly_report_for_today(db: Session) -> None:
    """It used to fail on every press: it read a field the cards do not have."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from geekvpn.presentation.bot.handlers.admin import today_report
    from geekvpn.presentation.bot.ui import admin_text as A

    db.add(_order(120_000, paid_at=datetime(2026, 11, 27, 1, 0, tzinfo=TEHRAN)))
    db.add(_order(90_000, paid_at=datetime(2026, 11, 26, 23, 0, tzinfo=TEHRAN)))  # yesterday
    db.commit()

    engine = create_async_engine(get_settings().postgres.dsn())
    try:
        async with async_sessionmaker(engine)() as session:
            body = await today_report(session, NOW.astimezone(UTC))
    finally:
        await engine.dispose()

    assert body.startswith(A.STATS_TODAY_TITLE)
    assert "۱۲۰٬۰۰۰" in body or "۱۲۰,۰۰۰" in body
    assert "۹۰" not in body.split("فروش امروز")[1].splitlines()[0]
