"""An approved reseller has to be able to reach the link they were sent.

`/set-password` is the one endpoint in the reseller flow whose caller has no
account yet, no session, and no reason to be on an approved network - they are
on their phone, at home, tapping a link from a chat.

It lived under `/api/v1/admin` at first, which works perfectly until somebody
configures `admin_ip_allowlist`. Then it returns 404 - deliberately, to avoid
confirming the admin API exists - to every reseller who was ever approved, and
the failure looks like a broken link rather than a policy.

That is the shape worth pinning: an endpoint whose test environment has the
control switched off, and whose production has it on.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.api.app import create_app

pytestmark = pytest.mark.integration

ADMIN_PREFIX = "/api/v1/admin"


def _paths() -> set[str]:
    return set(create_app().openapi()["paths"])


def test_setting_a_first_password_is_not_behind_the_admin_allowlist():
    """The allowlist protects everything under `/api/v1/admin`, and a reseller
    redeeming their link is on a home connection."""
    paths = {path for path in _paths() if path.endswith("/set-password")}

    assert paths, "the endpoint is gone"
    for path in paths:
        assert not path.startswith(ADMIN_PREFIX), path


def test_it_is_rate_limited_like_a_login():
    """Unauthenticated, and it takes a secret. It is the one reseller path
    somebody can hammer without an account, so it carries a login's ceiling
    rather than an admin mutation's."""
    from geekvpn.presentation.api.security_middleware import DEFAULT_ROUTE_POLICIES

    policies = dict(DEFAULT_ROUTE_POLICIES)

    assert "/api/v1/auth/set-password" in policies
    assert policies["/api/v1/auth/set-password"].startswith("auth.")


def test_reviewing_applications_stays_behind_it():
    """The other half. Approving somebody is an operator action and belongs on
    an approved network, whatever the endpoint next to it does."""
    review = {path for path in _paths() if "reseller-applications" in path}

    assert review
    for path in review:
        assert path.startswith(ADMIN_PREFIX), path
