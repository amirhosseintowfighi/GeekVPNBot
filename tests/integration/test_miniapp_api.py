"""The Mini App's authentication boundary.

Every route re-verifies the Telegram initData signature, so these assert the
part an attacker actually probes: what happens with no header, the wrong
scheme, and a forged signature.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

MINIAPP = "/api/miniapp"

#: Every route the Mini App can reach, so a new one cannot be added without an
#: authentication check.
PROTECTED = [
    f"{MINIAPP}/storefront",
    f"{MINIAPP}/subscriptions",
    f"{MINIAPP}/wallet",
    f"{MINIAPP}/referral",
    f"{MINIAPP}/tickets",
    f"{MINIAPP}/profile",
    f"{MINIAPP}/preferences",
    f"{MINIAPP}/servers",
    f"{MINIAPP}/faq",
]


@pytest.fixture
def api(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("path", PROTECTED)
def test_no_header_is_refused(api, path) -> None:
    assert api.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_a_bearer_token_is_not_accepted_where_initdata_is_required(api, path) -> None:
    """The Mini App scheme is `tma`. Accepting a Bearer here would let an
    access token stand in for a signature Telegram vouched for."""
    assert api.get(path, headers={"Authorization": "Bearer whatever"}).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_a_forged_signature_is_refused(api, path) -> None:
    forged = "user=%7B%22id%22%3A1%7D&auth_date=1&hash=deadbeef"
    assert api.get(path, headers={"Authorization": f"tma {forged}"}).status_code == 401


def test_an_empty_tma_value_is_refused(api) -> None:
    assert api.get(f"{MINIAPP}/wallet", headers={"Authorization": "tma "}).status_code == 401


def test_the_scheme_is_matched_case_insensitively(api) -> None:
    """Telegram's own SDK examples disagree about the capitalisation, so the
    refusal must come from the signature, not from the scheme's case."""
    forged = "user=%7B%22id%22%3A1%7D&auth_date=1&hash=deadbeef"
    lower = api.get(f"{MINIAPP}/wallet", headers={"Authorization": f"tma {forged}"})
    upper = api.get(f"{MINIAPP}/wallet", headers={"Authorization": f"TMA {forged}"})
    assert lower.status_code == upper.status_code == 401


def test_every_miniapp_route_requires_authentication(app) -> None:
    """No route may be reachable anonymously.

    Asserted against the schema rather than a list, so adding an endpoint
    without a customer on it fails here rather than in production.
    """
    schema = app.openapi()
    unprotected = []
    for path, operations in schema["paths"].items():
        if not path.startswith(f"{MINIAPP}/"):
            continue
        for method, operation in operations.items():
            params = {p.get("name") for p in operation.get("parameters", [])}
            if "authorization" not in params:
                unprotected.append(f"{method.upper()} {path}")
    assert not unprotected, unprotected
