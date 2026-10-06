"""Who the trial follow-up goes to, shop by shop, as the database answers it."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import AdminModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel
from geekvpn.infrastructure.persistence.models.resellers import ResellerModel
from geekvpn.infrastructure.persistence.repositories.sync_trial_takers import (
    trial_takers_without_purchase,
)

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
TRIED = NOW - timedelta(hours=10)

WAITING, BOUGHT_AFTER, TOO_RECENT, IN_RESELLER_SHOP, CONSOLE_TEST = 1, 2, 3, 4, -5
SHOP = uuid.uuid4()


def _order(
    user: int,
    *,
    source: str = "trial",
    placed: datetime = TRIED,
    reseller: uuid.UUID | None = None,
) -> OrderModel:
    return OrderModel(
        id=uuid.uuid4().hex,
        number=uuid.uuid4().hex[:12],
        user_id=user,
        state="active",
        source=source,
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        plan_name_fa="تست",
        duration_days=1,
        list_price=0,
        total=0,
        placed_at=placed,
        reseller_id=reseller,
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
        admin_id = uuid.uuid4()
        db.add(
            AdminModel(
                id=admin_id, username="shop", password_hash="x", role="reseller", status="active"
            )
        )
        db.flush()
        db.add(ResellerModel(id=SHOP, admin_id=admin_id, name_fa="شمال"))
        db.flush()
        db.add_all(
            [
                _order(WAITING),
                _order(BOUGHT_AFTER),
                _order(BOUGHT_AFTER, source="bot", placed=NOW - timedelta(hours=1)),
                _order(TOO_RECENT, placed=NOW - timedelta(hours=1)),
                _order(IN_RESELLER_SHOP, reseller=SHOP),
                _order(CONSOLE_TEST),
            ]
        )
        db.commit()
        yield db
    engine.dispose()


def test_our_shop_follows_up_its_own_trial_takers_who_did_not_buy(session: Session) -> None:
    window = (NOW - timedelta(days=3), NOW - timedelta(hours=6))

    assert trial_takers_without_purchase(session, None, *window) == [WAITING]


def test_a_reseller_shop_follows_up_only_its_own(session: Session) -> None:
    window = (NOW - timedelta(days=3), NOW - timedelta(hours=6))

    assert trial_takers_without_purchase(session, SHOP, *window) == [IN_RESELLER_SHOP]
