"""A wallet transfer as the database stores it: both entries, both balances."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.payments import WalletEntryModel
from geekvpn.infrastructure.persistence.repositories.sync_payments import SyncWalletRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"entry-{self.n}"


class _Quiet:
    def publish_all(self, events: object) -> None:
        pass

    def record(self, **_: object) -> None:
        pass


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
        yield db
    engine.dispose()


def test_a_transfer_writes_both_sides_and_both_balances(session: Session) -> None:
    repository = SyncWalletRepository(session)
    service = WalletService(
        wallets=repository,
        clock=_Clock(),  # type: ignore[arg-type]
        ids=_Ids(),  # type: ignore[arg-type]
        events=_Quiet(),  # type: ignore[arg-type]
        audit=_Quiet(),  # type: ignore[arg-type]
    )
    service.credit_reward(
        user_id=1, amount=Money(100_000), kind=TransactionKind.CASHBACK, description_fa="هدیه"
    )
    session.commit()

    service.transfer(from_user=1, to_user=2, amount=Money(40_000), reference="transfer:t1")
    session.commit()

    kinds = {
        (row.user_id, row.kind, row.amount)
        for row in session.execute(
            select(WalletEntryModel).where(WalletEntryModel.reference == "transfer:t1")
        ).scalars()
    }
    assert kinds == {(1, "transfer_out", -40_000), (2, "transfer_in", 40_000)}
    assert service.balance(1) == Money(60_000)
    assert service.balance(2) == Money(40_000)
