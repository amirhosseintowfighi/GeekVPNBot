"""Reading a screen must not spend the budget for the action it performs.

`admin.broadcast` allows five requests an hour, which is right for sending a
message to every customer and catastrophic for the page that lists them: the
prefix covered the list, the audience estimate and the send alike, so opening
the compose screen a few times locked the operator out of broadcasts for the
rest of the hour - including reading them.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.api.security_middleware import (
    DEFAULT_ROUTE_POLICIES,
    RateLimitMiddleware,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def choose():
    middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
    middleware._route_policies = DEFAULT_ROUTE_POLICIES
    middleware._default_policy = None
    return middleware._policy_name


def test_listing_broadcasts_is_charged_as_an_ordinary_admin_read(choose) -> None:
    assert choose("/api/v1/admin/broadcasts", "GET") == "admin.mutation"


def test_sending_a_broadcast_is_charged_as_a_broadcast(choose) -> None:
    assert choose("/api/v1/admin/broadcasts", "POST") == "admin.broadcast"


def test_estimating_an_audience_is_not_sending_to_it(choose) -> None:
    """A POST, but the compose screen fires one on every segment change."""
    assert choose("/api/v1/admin/broadcasts/estimate", "POST") == "admin.mutation"


def test_cancelling_a_broadcast_still_counts_against_the_send_budget(choose) -> None:
    assert choose("/api/v1/admin/broadcasts/abc/cancel", "POST") == "admin.broadcast"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_no_safe_method_can_exhaust_an_action_budget(choose, method: str) -> None:
    assert choose("/api/v1/admin/broadcasts", method) == "admin.mutation"


def test_the_ordinary_admin_surface_is_unaffected(choose) -> None:
    assert choose("/api/v1/admin/panels", "POST") == "admin.mutation"
    assert choose("/api/v1/admin/analytics/export", "GET") == "analytics.export"
