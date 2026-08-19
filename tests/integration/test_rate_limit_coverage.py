"""Every route is either rate limited or deliberately not.

The bug this exists to stop: the policy table keyed the Mini App on
``/api/v1/miniapp`` while the router is mounted at ``/api/miniapp``. Nothing
failed - the prefix simply matched no request, so sixteen endpoints including
checkout were exempt from rate limiting and no test noticed, because every test
asserted on the table rather than on the routes.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.security.throttling import Decision, Policy, policy_for
from geekvpn.presentation.api.security_middleware import (
    DEFAULT_ROUTE_POLICIES,
    EXEMPT_PATHS,
)

pytestmark = pytest.mark.integration

#: Routes that are knowingly unlimited, each with the reason. Anything not
#: covered by a policy and not listed here fails the test below - a new router
#: has to make the choice explicitly rather than inherit "unlimited" by default.
UNLIMITED_PATHS: frozenset[str] = frozenset(
    {
        # All four require an already-issued access token, so they are reachable
        # only by someone who has passed a limited login. Logging out more often
        # than intended costs the platform nothing.
        "/api/v1/auth/me",
        "/api/v1/auth/sessions",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        # A static build banner. No database work behind it.
        "/api/v1/info",
    }
)


#: Prefixes kept for routes that were specified but never mounted (the /api/v1
#: customer surface the Mini App replaced). Listed rather than deleted so the
#: limit is already in place if those routers are ever registered - but listed
#: explicitly, because an unlisted prefix that matches nothing is exactly the
#: bug this file exists to catch.
RESERVED_PREFIXES: frozenset[str] = frozenset(
    {
        "/api/v1/auth/captcha",
        "/api/v1/admin/broadcasts",
        "/api/v1/payments",
        "/api/v1/payments/receipt",
        "/api/v1/wallet",
        "/api/v1/support/search",
        "/api/v1/support/tickets",
    }
)


def _policy_name(path: str) -> str | None:
    """The middleware's own longest-prefix lookup, kept in step with it."""
    best: tuple[int, str] | None = None
    for prefix, name in DEFAULT_ROUTE_POLICIES:
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), name)
    return best[1] if best else None


def test_every_registered_route_is_limited_or_explicitly_exempt(app: FastAPI) -> None:
    unaccounted = [
        path
        for path in app.openapi()["paths"]
        if _policy_name(path) is None and path not in EXEMPT_PATHS and path not in UNLIMITED_PATHS
    ]

    assert unaccounted == [], (
        "These routes resolve to no rate limit policy. Add a prefix to "
        "DEFAULT_ROUTE_POLICIES, or list the path in UNLIMITED_PATHS with a reason."
    )


def test_every_policy_prefix_matches_at_least_one_route(app: FastAPI) -> None:
    """The other half of the same bug: a prefix that matches nothing.

    ``/api/v1/miniapp`` looked like a control in the table for as long as it
    existed and enforced nothing, which is the failure mode this whole audit
    keeps finding.
    """
    paths = list(app.openapi()["paths"])

    dead = [
        prefix
        for prefix, _ in DEFAULT_ROUTE_POLICIES
        if prefix not in RESERVED_PREFIXES and not any(path.startswith(prefix) for path in paths)
    ]

    assert dead == [], (
        "These policy prefixes match no registered route. Correct the prefix, "
        "or add it to RESERVED_PREFIXES if the router is not mounted yet."
    )


def test_every_named_policy_exists(app: FastAPI) -> None:
    for _, name in DEFAULT_ROUTE_POLICIES:
        policy_for(name)


class _RefusingLimiter:
    """Says no to everything, so a 429 proves the middleware ran at all."""

    async def check(self, policy: Policy, *, subject_id: str | None, ip: str | None) -> Decision:
        self.policy = policy
        return Decision(
            allowed=False,
            policy_name=policy.name,
            limit=policy.limit,
            remaining=0,
            retry_after_seconds=30,
        )


def test_a_mini_app_request_is_rate_limited(container: Container) -> None:
    from geekvpn.presentation.api.app import create_app

    limited = dataclasses.replace(container, sliding_limiter=_RefusingLimiter())  # type: ignore[arg-type]
    with TestClient(create_app(container=limited)) as client:
        response = client.get("/api/miniapp/storefront")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
