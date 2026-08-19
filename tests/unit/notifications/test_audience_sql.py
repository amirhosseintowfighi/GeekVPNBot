"""The audience queries must at least be valid SQL against the real schema.

`test_audience_resolver.py` proves the rules are right, and skips without
Postgres - which on a developer machine is always. This compiles the same
statements against the PostgreSQL dialect instead, so a column that does not
exist, or a type that cannot be compared, fails here rather than the first
time an operator presses send.

It caught `orders.total_amount`, which is called `total`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from geekvpn.domain.notifications.enums import AudienceKind
from geekvpn.domain.notifications.errors import UnknownAudience
from geekvpn.infrastructure.notifications.audiences import SqlAudienceResolver

pytestmark = pytest.mark.unit

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.fixture
def resolver() -> SqlAudienceResolver:
    # No session: every method under test builds a statement rather than
    # running one.
    return SqlAudienceResolver(session=None)  # type: ignore[arg-type]


def test_every_audience_query_compiles(resolver: SqlAudienceResolver) -> None:
    statements = [
        resolver._reachable(),
        resolver._with_live_subscription(NOW),
        resolver._with_expired_subscription(NOW),
        resolver._expiring_within(7, NOW),
        resolver._with_paid_order(),
        resolver._in_tier("silver"),
    ]
    for statement in statements:
        assert "SELECT" in compiled(statement)


def test_the_tier_query_reads_the_column_orders_actually_has(
    resolver: SqlAudienceResolver,
) -> None:
    """Spend is summed from `orders.total`.

    This was written against `orders.total_amount`, which does not exist. The
    statement built fine and would have failed at execution - on the one code
    path an operator reaches by pressing send to a paying segment.
    """
    sql = compiled(resolver._in_tier("silver"))

    assert "orders.total" in sql
    assert "total_amount" not in sql


def test_a_tier_is_bounded_on_both_sides(resolver: SqlAudienceResolver) -> None:
    """Two HAVING clauses for a middle tier, one for the top."""
    assert compiled(resolver._in_tier("silver")).count("HAVING") >= 1
    assert ">=" in compiled(resolver._in_tier("silver"))
    assert "<" in compiled(resolver._in_tier("silver"))
    # Diamond is the top tier: nothing above it to bound against.
    assert "<" not in compiled(resolver._in_tier("diamond")).split("HAVING")[1]


def test_only_active_customers_are_reachable(resolver: SqlAudienceResolver) -> None:
    sql = compiled(resolver._reachable())

    assert "users.status" in sql
    assert "ORDER BY users.telegram_id" in sql


def test_an_unknown_tier_raises_rather_than_widening_the_audience(
    resolver: SqlAudienceResolver,
) -> None:
    with pytest.raises(UnknownAudience):
        resolver._in_tier("platinum")


def test_an_explicit_reference_of_nothing_resolves_to_nobody(
    resolver: SqlAudienceResolver,
) -> None:
    """Never "everyone" by accident.

    An empty or unparseable id list must be an empty audience, not a missing
    filter - which is what would turn a targeted note into a message to the
    whole book.
    """
    assert resolver.resolve(AudienceKind.EXPLICIT, reference=None) == []
    assert resolver.resolve(AudienceKind.EXPLICIT, reference="") == []
    assert resolver.resolve(AudienceKind.EXPLICIT, reference="not-an-id, also-not") == []
