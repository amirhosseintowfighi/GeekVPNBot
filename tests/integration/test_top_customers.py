"""The four ladders an operator can look at, ranked by the database."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.infrastructure.analytics.top_customers import Ladder, top
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.payments import WalletEntryModel
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
SMALL, BIG = 1, 2


def order(number: str, user: int, total: int, state: str = "active") -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=number,
        user_id=user,
        state=state,
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa="ماهانه",
        duration_days=30,
        list_price=total,
        total=total,
        placed_at=NOW,
    )


def entry(eid: str, user: int, kind: str, amount: int) -> WalletEntryModel:
    return WalletEntryModel(
        id=eid,
        user_id=user,
        kind=kind,
        amount=amount,
        balance_after=0,
        occurred_at=NOW,
        description_fa="",
    )


def sub(sid: str, user: int) -> SubscriptionModel:
    return SubscriptionModel(
        id=sid,
        user_id=user,
        state="active",
        remote_username=sid,
        started_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=29),
        traffic_used_mib=0,
        device_limit=1,
        notified_expiry_days=[],
        notified_traffic_percents=[],
    )


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(get_settings().postgres.dsn(driver="postgresql+psycopg"))
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
        for telegram_id, name in ((SMALL, "کم"), (BIG, "زیاد")):
            db.add(
                UserModel(
                    id=uuid.uuid4(),
                    telegram_id=telegram_id,
                    first_name=name,
                    status="active",
                    referral_code=f"r{telegram_id}",
                    language="fa",
                )
            )
        db.add_all(
            [
                order("A", SMALL, 100_000),
                order("B", BIG, 300_000),
                order("C", BIG, 900_000, state="cancelled"),
                order("D", SMALL, 150_000),
                sub("s1", BIG),
                sub("s2", BIG),
                sub("s3", SMALL),
                entry("e1", SMALL, "topup", 500_000),
                entry("e2", BIG, "topup", 100_000),
                entry("e3", SMALL, "purchase", -450_000),
            ]
        )
        db.commit()
        yield db
    engine.dispose()


def ranking(session: Session, ladder: Ladder) -> list[tuple[int, int]]:
    return [(r.telegram_id, r.value) for r in top(session, ladder, now=NOW)]


def test_spending_counts_only_money_that_was_taken(session: Session) -> None:
    assert ranking(session, Ladder.SPENT) == [(BIG, 300_000), (SMALL, 250_000)]


def test_live_services_are_counted_per_customer(session: Session) -> None:
    assert ranking(session, Ladder.SERVICES) == [(BIG, 2), (SMALL, 1)]


def test_top_ups_and_balances_are_different_ladders(session: Session) -> None:
    assert ranking(session, Ladder.TOPPED_UP) == [(SMALL, 500_000), (BIG, 100_000)]
    assert ranking(session, Ladder.BALANCE) == [(BIG, 100_000), (SMALL, 50_000)]


def test_each_rung_carries_a_name(session: Session) -> None:
    assert [r.name for r in top(session, Ladder.SERVICES, now=NOW)] == ["زیاد", "کم"]
