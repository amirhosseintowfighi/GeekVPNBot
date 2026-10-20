"""Which payments the gateway sweep asks about, as the database answers it."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.payments.gateway_verification import waiting_at_a_gateway
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.payments import InvoiceModel, PaymentModel

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


@pytest.fixture
def engine() -> Iterator[Any]:
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
    yield engine
    engine.dispose()


def _payment(pid: str, *, state: str, age: timedelta) -> list[Any]:
    created = NOW - age
    invoice = InvoiceModel(
        id=f"inv-{pid}",
        number=f"1405-{pid}",
        user_id=1,
        state="open",
        subject_fa="شارژ",
        lines=[],
        issued_at=created,
        created_at=created,
        updated_at=created,
    )
    payment = PaymentModel(
        id=pid,
        invoice_id=invoice.id,
        user_id=1,
        method="gateway",
        state=state,
        amount=250_000,
        gateway_key="atlaspay",
        gateway_reference="66",
        created_at=created,
        updated_at=created,
    )
    return [invoice, payment]


def test_only_recent_payments_still_at_a_gateway_are_asked_about(engine: Any) -> None:
    with Session(engine) as db:
        for rows in (
            _payment("waiting", state="pending_gateway", age=timedelta(minutes=5)),
            _payment("settled", state="approved", age=timedelta(minutes=5)),
            _payment("ancient", state="pending_gateway", age=timedelta(days=3)),
        ):
            db.add(rows[0])
            db.flush()
            db.add(rows[1])
        db.commit()

    @contextmanager
    def sessions() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    container = SimpleNamespace(sync_sessions=sessions, clock=SimpleNamespace(now=lambda: NOW))

    assert waiting_at_a_gateway(container) == ["waiting"]  # type: ignore[arg-type]
