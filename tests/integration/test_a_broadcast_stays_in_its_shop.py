"""A reseller's broadcast reaches the reseller's customers and nobody else.

The resolver ignored the shop. A reseller who sent an announcement reached
every active customer on the platform - through the reseller's bot, under the
reseller's name - and the platform's own "everyone" reached every reseller's
customers too.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from geekvpn.domain.notifications.enums import AudienceKind
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.notifications.audiences import SqlAudienceResolver
from geekvpn.infrastructure.persistence.base import Base
from geekvpn.infrastructure.persistence.models.identity import AdminModel, UserModel
from geekvpn.infrastructure.persistence.models.resellers import ResellerModel

pytestmark = pytest.mark.integration

PLATFORM_CUSTOMER = 111
SHOP_CUSTOMER = 222


@pytest.fixture
def world() -> Iterator[tuple[Session, uuid.UUID]]:
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

    with Session(engine) as session:
        admin = AdminModel(
            id=uuid.uuid4(), username="shop", password_hash="x", role="reseller", status="active"
        )
        session.add(admin)
        session.flush()
        shop = ResellerModel(id=uuid.uuid4(), admin_id=admin.id, name_fa="فروشگاه")
        session.add(shop)
        session.flush()
        for telegram_id, reseller_id in ((PLATFORM_CUSTOMER, None), (SHOP_CUSTOMER, shop.id)):
            session.add(
                UserModel(
                    id=uuid.uuid4(),
                    telegram_id=telegram_id,
                    reseller_id=reseller_id,
                    status="active",
                    referral_code=f"r{telegram_id}",
                    language="fa",
                )
            )
        session.commit()
        yield session, shop.id
    engine.dispose()


def test_a_resellers_everyone_is_only_their_own_customers(
    world: tuple[Session, uuid.UUID],
) -> None:
    session, shop_id = world

    audience = SqlAudienceResolver(session, reseller_id=shop_id).resolve(AudienceKind.ALL)

    assert audience == [SHOP_CUSTOMER]


def test_the_platforms_everyone_leaves_resellers_customers_alone(
    world: tuple[Session, uuid.UUID],
) -> None:
    session, _ = world

    audience = SqlAudienceResolver(session).resolve(AudienceKind.ALL)

    assert audience == [PLATFORM_CUSTOMER]


def test_an_explicit_list_cannot_reach_across_shops(world: tuple[Session, uuid.UUID]) -> None:
    session, shop_id = world

    audience = SqlAudienceResolver(session, reseller_id=shop_id).resolve(
        AudienceKind.EXPLICIT, reference=f"{PLATFORM_CUSTOMER},{SHOP_CUSTOMER}"
    )

    assert audience == [SHOP_CUSTOMER]
