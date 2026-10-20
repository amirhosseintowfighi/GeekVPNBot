"""iSunnyMoney's order ids come from the database: 100001, then up by one."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.di.sync_scope import build_gateway_registry
from geekvpn.infrastructure.persistence import types as persistence_types
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.payments import GatewayAccountModel
from geekvpn.infrastructure.persistence.types import install_keyring
from geekvpn.infrastructure.security.crypto import KeyRing

pytestmark = pytest.mark.integration


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
    # The merchant key column is encrypted, as in production.
    keyring = KeyRing.from_master_secret("t" * 48)
    previous = persistence_types._keyring_provider
    install_keyring(lambda: keyring)
    with Session(engine) as db:
        db.add(
            GatewayAccountModel(
                id="g1", provider="isunnymoney", merchant_id_encrypted="key", active=True
            )
        )
        db.commit()
        yield db
    # Put back whatever was installed, so tests after this one see no change.
    persistence_types._keyring_provider = previous
    engine.dispose()


def test_the_registered_gateway_draws_ids_from_100001(session: Session) -> None:
    gateway: Any = build_gateway_registry(session).get("isunnymoney")

    assert [gateway.next_order_id() for _ in range(3)] == [100001, 100002, 100003]
