"""Who a broadcast actually reaches.

The audience rules are the part of broadcasting that can be wrong in a way
nobody notices until it has already gone out: a promotional message to a
suspended account, a "your service has ended" to someone who renewed an hour
ago, or - the expensive one - the same person in two overlapping segments.

These need a real database because they are SQL, not logic. They skip without
Postgres, which is why `test_audience_reference_parsing.py` exists alongside
them for the parts that are pure: tests/unit/notifications/test_audience_sql.py.
"""

from __future__ import annotations

import uuid
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
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine(
        get_settings().postgres.dsn(driver="postgresql+psycopg"), pool_pre_ping=True
    )
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)

    with Session(engine) as opened:
        yield opened
    engine.dispose()


def add_user(session: Session, telegram_id: int, *, status: str = "active") -> None:
    session.add(
        UserModel(
            id=uuid.uuid4(),
            telegram_id=telegram_id,
            status=status,
            referral_code=f"ref{telegram_id}",
            language="fa",
        )
    )
    session.flush()


def add_subscription(
    session: Session, telegram_id: int, *, state: str, expires_at: datetime
) -> None:
    session.add(
        SubscriptionModel(
            id=uuid.uuid4(),
            user_id=telegram_id,
            plan_id=uuid.uuid4(),
            state=state,
            started_at=expires_at - timedelta(days=30),
            expires_at=expires_at,
            device_limit=1,
        )
    )
    session.flush()


def add_paid_order(session: Session, telegram_id: int, *, total: int) -> None:
    session.add(
        OrderModel(
            id=uuid.uuid4(),
            number=f"ORD-{telegram_id}-{total}",
            user_id=telegram_id,
            state="active",
            plan_id=uuid.uuid4(),
            duration_days=30,
            device_limit=1,
            list_price=total,
            discount=0,
            total=total,
            placed_at=NOW - timedelta(days=10),
        )
    )
    session.flush()


def test_a_suspended_customer_is_in_no_audience(session: Session) -> None:
    """The rule that matters most, because breaking it is a support thread.

    Messaging somebody the moment after closing their account is how a quiet
    suspension becomes an argument.
    """
    add_user(session, 111)
    add_user(session, 222, status="suspended")
    add_user(session, 333, status="banned")

    resolved = SqlAudienceResolver(session).resolve(AudienceKind.ALL)

    assert resolved == [111]


def test_someone_who_renewed_is_not_told_their_service_ended(session: Session) -> None:
    """EXPIRED means "lapsed and still lapsed".

    A customer with an old expired subscription and a current live one has not
    churned; sending them a win-back is how a renewal turns into a refund
    request.
    """
    add_user(session, 111)
    add_user(session, 222)
    # 111 lapsed and came back. 222 lapsed and stayed away.
    add_subscription(session, 111, state="expired", expires_at=NOW - timedelta(days=40))
    add_subscription(session, 111, state="active", expires_at=NOW + timedelta(days=20))
    add_subscription(session, 222, state="expired", expires_at=NOW - timedelta(days=5))

    resolved = SqlAudienceResolver(session).resolve(AudienceKind.EXPIRED)

    assert resolved == [222]


def test_expiring_soon_excludes_what_has_already_expired(session: Session) -> None:
    add_user(session, 111)
    add_user(session, 222)
    add_user(session, 333)
    add_subscription(session, 111, state="active", expires_at=NOW + timedelta(days=3))
    add_subscription(session, 222, state="active", expires_at=NOW + timedelta(days=60))
    add_subscription(session, 333, state="active", expires_at=NOW - timedelta(days=1))

    resolved = SqlAudienceResolver(session).resolve(AudienceKind.EXPIRING_SOON)

    assert resolved == [111]


def test_never_purchased_means_no_money_ever_arrived(session: Session) -> None:
    add_user(session, 111)
    add_user(session, 222)
    add_paid_order(session, 222, total=500_000)

    resolved = SqlAudienceResolver(session).resolve(AudienceKind.NEVER_PURCHASED)

    assert resolved == [111]


def test_a_tier_is_bounded_above_as_well_as_below(session: Session) -> None:
    """ "Silver" must mean silver, not "silver and everyone richer".

    Without the upper bound a discount aimed at the middle of the book lands
    on the customers who least need it.
    """
    add_user(session, 111)
    add_user(session, 222)
    add_user(session, 333)
    add_paid_order(session, 111, total=500_000)  # bronze
    add_paid_order(session, 222, total=1_500_000)  # silver
    add_paid_order(session, 333, total=5_000_000)  # gold

    resolved = SqlAudienceResolver(session).resolve(AudienceKind.TIER, reference="silver")

    assert resolved == [222]


def test_an_explicit_list_is_still_filtered_for_reachability(session: Session) -> None:
    """An operator pasting ids from a spreadsheet cannot know who is suspended."""
    add_user(session, 111)
    add_user(session, 222, status="suspended")

    resolved = SqlAudienceResolver(session).resolve(
        AudienceKind.EXPLICIT, reference="111, 222, 999"
    )

    assert resolved == [111]


def test_an_unknown_tier_is_refused_rather_than_resolved_to_everyone(session: Session) -> None:
    """The dangerous failure mode: a typo that silently widens the audience."""
    add_user(session, 111)

    with pytest.raises(UnknownAudience):
        SqlAudienceResolver(session).resolve(AudienceKind.TIER, reference="platinum")


def test_the_cap_is_enforced(session: Session) -> None:
    for telegram_id in range(1, 6):
        add_user(session, telegram_id)

    resolved = SqlAudienceResolver(session, limit=3).resolve(AudienceKind.ALL)

    assert resolved == [1, 2, 3]
