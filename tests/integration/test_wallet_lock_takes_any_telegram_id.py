"""A wallet spend works for every Telegram id, not only the old ones.

The lock that serialises a customer's spends was taken as
`pg_advisory_xact_lock(int4, int4)` with the Telegram id as the second key.
Accounts created in recent years have ids past 2^31 - production has
6215538602 among its buyers - and for them Postgres found no such function:
every wallet purchase, top-up settlement and transfer failed with a database
error. Ids that fit keep the exact keys they had, so a lock held across a
deploy still collides with itself.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.repositories.sync_payments import (
    WALLET_LOCK_NAMESPACE,
    SyncWalletRepository,
    wallet_lock_keys,
)

pytestmark = pytest.mark.integration

INT4_MAX = 2_147_483_647


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(get_settings().postgres.dsn(driver="postgresql+psycopg"))
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")
    with Session(engine) as db:
        yield db
        db.rollback()
    engine.dispose()


@pytest.mark.parametrize("telegram_id", [943_630_532, 6_215_538_602, 8_999_999_999_999])
def test_the_lock_is_taken_for_any_telegram_id(session: Session, telegram_id: int) -> None:
    SyncWalletRepository(session).lock(telegram_id)


def test_an_id_that_fits_keeps_the_keys_it_always_had() -> None:
    assert wallet_lock_keys(943_630_532) == (WALLET_LOCK_NAMESPACE % INT4_MAX, 943_630_532)


@pytest.mark.parametrize("telegram_id", [1, 2_147_483_647, 2_147_483_648, 6_215_538_602])
def test_both_keys_fit_a_postgres_integer(telegram_id: int) -> None:
    first, second = wallet_lock_keys(telegram_id)
    assert 0 <= first <= INT4_MAX
    assert 0 <= second <= INT4_MAX


def test_two_customers_never_share_a_lock() -> None:
    ids = [2_147_483_647, 2_147_483_648, 4_294_967_295, 4_294_967_296, 6_215_538_602, 15]
    assert len({wallet_lock_keys(i) for i in ids}) == len(ids)
