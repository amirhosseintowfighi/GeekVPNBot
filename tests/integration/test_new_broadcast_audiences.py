"""The audiences an operator asked for by name: nobody with a service, one
server's customers, and customers whose service is switched off."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.domain.notifications.enums import AudienceKind
from geekvpn.domain.notifications.errors import UnknownAudience
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.notifications.audiences import SqlAudienceResolver
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.provisioning import NodeModel, SubscriptionModel

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
ON_GERMANY, ON_FINLAND, SUSPENDED, NOTHING = 1, 2, 3, 4


def sub(sid: str, user: int, *, node: str | None, state: str = "active") -> SubscriptionModel:
    return SubscriptionModel(
        id=sid,
        user_id=user,
        state=state,
        node_id=node,
        remote_username=sid,
        started_at=NOW - timedelta(days=5),
        expires_at=NOW + timedelta(days=25),
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
        for node_id in ("de", "fi"):
            db.add(
                NodeModel(
                    id=node_id,
                    name_fa=node_id,
                    panel_kind="marzban",
                    base_url="https://x",
                    state="maintenance",
                )
            )
        for telegram_id in (ON_GERMANY, ON_FINLAND, SUSPENDED, NOTHING):
            db.add(
                UserModel(
                    id=uuid.uuid4(),
                    telegram_id=telegram_id,
                    status="active",
                    referral_code=f"r{telegram_id}",
                    language="fa",
                )
            )
        db.flush()
        db.add_all(
            [
                sub("s1", ON_GERMANY, node="de"),
                sub("s2", ON_FINLAND, node="fi"),
                sub("s3", SUSPENDED, node="de", state="suspended"),
            ]
        )
        db.commit()
        yield db
    engine.dispose()


def test_no_service_is_everyone_without_a_working_one(session: Session) -> None:
    assert SqlAudienceResolver(session).resolve(AudienceKind.NO_SERVICE) == [SUSPENDED, NOTHING]


def test_one_server_is_only_that_servers_working_services(session: Session) -> None:
    assert SqlAudienceResolver(session).resolve(AudienceKind.ON_SERVER, reference="de") == [
        ON_GERMANY
    ]


def test_a_server_audience_without_a_server_is_refused(session: Session) -> None:
    with pytest.raises(UnknownAudience):
        SqlAudienceResolver(session).resolve(AudienceKind.ON_SERVER)


def test_suspended_services_are_their_own_audience(session: Session) -> None:
    assert SqlAudienceResolver(session).resolve(AudienceKind.SUSPENDED_SERVICE) == [SUSPENDED]
