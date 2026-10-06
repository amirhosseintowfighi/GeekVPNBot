"""Who the newcomer gift goes to, as the database answers it."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.application.payments.newcomer_gift import REFERENCE
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import AdminModel, UserModel
from geekvpn.infrastructure.persistence.models.payments import WalletEntryModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel
from geekvpn.infrastructure.persistence.models.resellers import ResellerModel
from geekvpn.infrastructure.persistence.repositories.sync_newcomers import (
    newcomers_without_purchase,
)

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
JOINED = NOW - timedelta(hours=30)

WAITING, BOUGHT, ONLY_TRIED, GIFTED, TOO_NEW, RESELLERS, SUSPENDED = 1, 2, 3, 4, 5, 6, 7


def _order(user: int, *, source: str = "bot", state: str = "active") -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=f"1405-{user:04d}-{source}",
        user_id=user,
        state=state,
        source=source,
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa="ماهانه",
        duration_days=30,
        list_price=0 if source == "trial" else 200_000,
        total=0 if source == "trial" else 200_000,
        placed_at=JOINED,
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
        reseller_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        db.add(
            AdminModel(
                id=admin_id, username="shop", password_hash="x", role="reseller", status="active"
            )
        )
        db.flush()
        db.add(ResellerModel(id=reseller_id, admin_id=admin_id, name_fa="شمال"))
        db.flush()
        people = {
            WAITING: (JOINED, None, "active"),
            BOUGHT: (JOINED, None, "active"),
            ONLY_TRIED: (JOINED, None, "active"),
            GIFTED: (JOINED, None, "active"),
            TOO_NEW: (NOW - timedelta(hours=2), None, "active"),
            RESELLERS: (JOINED, reseller_id, "active"),
            SUSPENDED: (JOINED, None, "suspended"),
        }
        for telegram_id, (joined, shop, status) in people.items():
            db.add(
                UserModel(
                    id=uuid.uuid4(),
                    telegram_id=telegram_id,
                    status=status,
                    referral_code=f"r{telegram_id}",
                    language="fa",
                    reseller_id=shop,
                    created_at=joined,
                )
            )
        db.add_all([_order(BOUGHT), _order(ONLY_TRIED, source="trial")])
        db.add(
            WalletEntryModel(
                id="w1",
                user_id=GIFTED,
                kind="cashback",
                amount=20_000,
                balance_after=20_000,
                occurred_at=NOW,
                description_fa="هدیه",
                reference=REFERENCE,
            )
        )
        db.commit()
        yield db
    engine.dispose()


def test_only_a_recent_platform_customer_who_never_bought_or_got_it_is_due(
    session: Session,
) -> None:
    due = newcomers_without_purchase(
        session, NOW - timedelta(days=7), NOW - timedelta(hours=24)
    )

    # Someone who only took a free trial is exactly who the gift is for.
    assert sorted(due) == [WAITING, ONLY_TRIED]
