"""Two callers changing one payment run one after the other, never together.

`ReviewService.approve` said two operators clicking approve at once would
meet the state machine. They did not: each loaded the payment without a lock,
both saw "pending review", both approved and both committed. On a wallet
top-up that credited the customer twice. The same race was open between a
gateway's callback and the sweeper verifying one payment, and between a
double tap on the approve button, which Telegram delivers as two updates.

Every change to a payment loads it through `require_payment`, which now takes
the row lock. The second caller waits for the first to commit, then sees the
payment it left behind and is refused by the state machine.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.application.payments.loaders import require_payment
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence.repositories.sync_payments import SyncPaymentRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(get_settings().postgres.dsn(driver="postgresql+psycopg"))
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1 FROM billing_payments LIMIT 0"))
    except OperationalError as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")
    except Exception as exc:  # no schema
        pytest.skip(f"no payment tables: {exc.__class__.__name__}")
    yield engine
    engine.dispose()


@pytest.fixture
def payment_id(engine: Engine) -> Iterator[str]:
    invoice, payment = uuid.uuid4().hex, uuid.uuid4().hex
    with engine.begin() as cx:
        cx.execute(
            text(
                "INSERT INTO billing_invoices (id, number, user_id, issued_at) "
                "VALUES (:i, :n, 6215538602, now())"
            ),
            {"i": invoice, "n": f"T-{invoice[:12]}"},
        )
        cx.execute(
            text(
                "INSERT INTO billing_payments (id, invoice_id, user_id, method, state, amount) "
                "VALUES (:p, :i, 6215538602, 'card', 'pending_review', 100000)"
            ),
            {"p": payment, "i": invoice},
        )
    yield payment
    with engine.begin() as cx:
        cx.execute(text("DELETE FROM billing_payments WHERE id = :p"), {"p": payment})
        cx.execute(text("DELETE FROM billing_invoices WHERE id = :i"), {"i": invoice})


def test_a_second_caller_waits_while_the_first_holds_the_payment(
    engine: Engine, payment_id: str
) -> None:
    with Session(engine) as first, Session(engine) as second:
        require_payment(SyncPaymentRepository(first), payment_id)

        second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(OperationalError, match="lock timeout"):
            require_payment(SyncPaymentRepository(second), payment_id)

        first.rollback()
        second.rollback()


def test_once_the_first_is_done_the_second_proceeds(engine: Engine, payment_id: str) -> None:
    with Session(engine) as first, Session(engine) as second:
        require_payment(SyncPaymentRepository(first), payment_id)
        first.commit()

        second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        assert require_payment(SyncPaymentRepository(second), payment_id).id == payment_id
        second.rollback()
