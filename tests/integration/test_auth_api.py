"""HTTP-level authentication and authorization.

These tests exercise the real FastAPI dependency chain - bearer parsing, token
decoding, revocation check, permission enforcement, problem+json shape - with
fake persistence underneath. They are the closest thing to "what an attacker
sees" that runs without Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.infrastructure.security import csrf
from geekvpn.presentation.api.app import API_V1_PREFIX
from geekvpn.presentation.api.text_fa import GENERIC, persian_for

PROBLEM = "application/problem+json"
OPENAPI_URL = f"{API_V1_PREFIX}/openapi.json"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def issue_access(container, *, subject_type=SubjectType.ADMIN, role=None, permissions=()):
    return container.access_tokens.issue(
        subject_type=subject_type,
        subject_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role=role,
        permissions=list(permissions),
    ).value


@pytest.fixture
def auth_client(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# -- unauthenticated access -----------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/auth/sessions",
        "/api/v1/admin/auth/me",
        "/api/v1/admin/settings",
        "/api/v1/admin/audit-logs",
    ],
)
def test_protected_endpoints_require_a_token(auth_client, path):
    response = auth_client.get(path)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM)
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")


def test_a_malformed_authorization_header_is_a_401(auth_client):
    response = auth_client.get("/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401


def test_a_forged_token_is_a_401(auth_client):
    response = auth_client.get("/api/v1/auth/me", headers=bearer("a.b.c"))
    assert response.status_code == 401


def test_a_token_signed_with_another_key_is_a_401(auth_client):
    from datetime import timedelta

    from geekvpn.infrastructure.security.jwt import JwtAccessTokenService

    rogue = JwtAccessTokenService(
        secret_key="x" * 48,
        issuer="geekvpn",
        audience="geekvpn-clients",
        ttl=timedelta(minutes=15),
    )
    token = rogue.issue(
        subject_type=SubjectType.ADMIN,
        subject_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role=AdminRole.SUPER_ADMIN.value,
        permissions=[p.value for p in Permission],
    ).value

    assert auth_client.get("/api/v1/admin/auth/me", headers=bearer(token)).status_code == 401


# -- error contract --------------------------------------------------------


def test_errors_are_problem_json(auth_client):
    body = auth_client.get("/api/v1/auth/me").json()

    # `title` carries the machine-readable code; see the contract documented at
    # the top of presentation/api/errors.py.
    assert set(body) >= {"type", "title", "status", "instance", "correlation_id"}
    assert body["status"] == 401


def test_an_error_body_carries_the_persian_sentence_the_clients_render(auth_client):
    """Both frontends render `message_fa` and nothing else. While no handler
    sent it, a wrong password reached the operator as "your session expired"."""
    body = auth_client.get("/api/v1/auth/me").json()

    assert body["message_fa"] == persian_for("unauthenticated")
    assert body["message_fa"] != GENERIC


def test_error_bodies_never_leak_internals(auth_client):
    body = auth_client.get("/api/v1/auth/me").text.lower()
    for leak in ("traceback", "sqlalchemy", "secret", "password"):
        assert leak not in body


def test_a_correlation_id_is_returned_on_errors(auth_client):
    response = auth_client.get("/api/v1/auth/me")
    assert response.headers.get("X-Request-ID")


# -- login input validation ------------------------------------------------


def test_mini_app_login_rejects_an_empty_body(auth_client):
    assert auth_client.post("/api/v1/auth/telegram/mini-app", json={}).status_code == 422


def test_mini_app_login_rejects_a_bad_signature(auth_client):
    response = auth_client.post(
        "/api/v1/auth/telegram/mini-app", json={"init_data": "user=%7B%7D&hash=deadbeef"}
    )
    assert response.status_code == 401


def test_refresh_without_a_csrf_token_is_refused_before_the_token_is_looked_up(auth_client):
    response = auth_client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert response.status_code == 403


def test_refresh_rejects_an_unknown_token(auth_client, settings):
    # The double-submit token is bound to the presented refresh cookie, so both
    # cookies have to agree before the handler is reached at all.
    unknown = "u" * 40  # long enough to pass the schema, so the 401 is the lookup
    auth_client.cookies.set(csrf.REFRESH_COOKIE_NAME, unknown)
    token = csrf.issue_token(settings.jwt_secret, session_id=unknown[:64])
    auth_client.cookies.set(csrf.COOKIE_NAME, token)

    response = auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": unknown},
        headers={csrf.HEADER_NAME: token},
    )
    assert response.status_code == 401


def test_admin_login_rejects_a_short_password_before_touching_the_database(auth_client):
    response = auth_client.post("/api/v1/admin/auth/login", json={"username": "a", "password": "x"})
    assert response.status_code == 422


def test_admin_login_with_unknown_credentials_is_a_401(auth_client):
    response = auth_client.post(
        "/api/v1/admin/auth/login",
        json={"username": "ghost", "password": "a-sufficiently-long-password"},
    )
    assert response.status_code in {401, 429}


# -- authorization ---------------------------------------------------------


def test_a_customer_token_cannot_reach_admin_endpoints(auth_container, auth_client):
    """Subject-type confusion is the cheapest privilege escalation there is."""
    token = issue_access(auth_container, subject_type=SubjectType.USER)

    response = auth_client.get("/api/v1/admin/auth/me", headers=bearer(token))

    assert response.status_code in {401, 403}


def test_an_admin_token_cannot_use_customer_only_endpoints(auth_container, auth_client):
    token = issue_access(
        auth_container, subject_type=SubjectType.ADMIN, role=AdminRole.VIEWER.value
    )
    response = auth_client.get("/api/v1/auth/me", headers=bearer(token))
    assert response.status_code in {401, 403}


def test_an_admin_without_the_permission_is_refused(auth_container, auth_client):
    """A viewer holds `settings.read` but never `settings.write`."""
    token = issue_access(
        auth_container,
        subject_type=SubjectType.ADMIN,
        role=AdminRole.VIEWER.value,
        permissions=[Permission.SETTINGS_READ.value],
    )

    response = auth_client.put(
        "/api/v1/admin/settings/platform.maintenance_mode",
        json={"value": True},
        headers=bearer(token),
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith(PROBLEM)


def test_permissions_are_read_from_the_token_not_guessed_from_the_role(auth_container, auth_client):
    """A role claim alone must not grant anything; the permission list rules."""
    token = issue_access(
        auth_container,
        subject_type=SubjectType.ADMIN,
        role=AdminRole.SUPER_ADMIN.value,
        permissions=[],
    )

    response = auth_client.get("/api/v1/admin/audit-logs", headers=bearer(token))

    assert response.status_code == 403


def test_creating_an_admin_requires_admins_write(auth_container, auth_client):
    token = issue_access(
        auth_container,
        subject_type=SubjectType.ADMIN,
        role=AdminRole.ADMIN.value,
        permissions=[Permission.USERS_READ.value],
    )

    response = auth_client.post(
        "/api/v1/admin/admins",
        json={
            "username": "newbie",
            "password": "a-sufficiently-long-password",
            "role": "support",
        },
        headers=bearer(token),
    )

    assert response.status_code == 403


# -- public surface stays public ------------------------------------------


@pytest.mark.parametrize("path", ["/health/live", "/health/ready", "/api/v1/info"])
def test_operational_endpoints_remain_unauthenticated(auth_client, path):
    assert auth_client.get(path).status_code in {200, 503}


def test_the_openapi_document_declares_bearer_security(auth_client):
    schema = auth_client.get(OPENAPI_URL).json()
    assert "BearerAuth" in schema.get("components", {}).get("securitySchemes", {})


def test_every_auth_route_is_registered(auth_client):
    paths = auth_client.get(OPENAPI_URL).json()["paths"]
    for expected in (
        "/api/v1/auth/telegram/mini-app",
        "/api/v1/auth/telegram/widget",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        "/api/v1/auth/me",
        "/api/v1/auth/sessions",
        "/api/v1/admin/auth/login",
        "/api/v1/admin/auth/me",
        "/api/v1/admin/admins",
        "/api/v1/admin/audit-logs",
        "/api/v1/admin/settings",
    ):
        assert expected in paths


# -- the admin panel's cookie transport -----------------------------------


def test_the_admin_panel_authenticates_with_its_cookie_and_no_bearer_header(
    auth_container, auth_client
):
    """The panel holds no token: it sends `credentials: 'include'` and nothing else.

    A header-only check meant a correctly signed-in operator was still 401 on
    every request, which is why the panel bounced between the dashboard and a
    sign-in page forever.
    """
    token = issue_access(
        auth_container,
        subject_type=SubjectType.ADMIN,
        role=AdminRole.VIEWER.value,
        permissions=[Permission.SETTINGS_READ.value],
    )
    auth_client.cookies.set("geekvpn_admin_access", token)

    response = auth_client.get("/api/v1/admin/settings")

    assert response.status_code == 200


def test_a_customer_cookie_still_cannot_reach_an_admin_endpoint(auth_container, auth_client):
    """The cookie is a transport, not a promotion: subject type is still checked."""
    token = issue_access(auth_container, subject_type=SubjectType.USER)
    auth_client.cookies.set("geekvpn_admin_access", token)

    response = auth_client.get("/api/v1/admin/auth/me")

    assert response.status_code in {401, 403}


def test_signing_out_clears_both_session_cookies(auth_container, auth_client):
    """The panel's sign-out button had no endpoint to call at all.

    Revocation itself is `sessions.revoke`, shared with the customer logout and
    covered there; what this pins is that the route exists, is admin-only, and
    does not leave a live cookie in the browser afterwards.
    """
    token = issue_access(
        auth_container,
        subject_type=SubjectType.ADMIN,
        role=AdminRole.VIEWER.value,
        permissions=[Permission.SETTINGS_READ.value],
    )
    auth_client.cookies.set("geekvpn_admin_access", token)

    response = auth_client.post("/api/v1/admin/auth/sign-out")

    assert response.status_code == 200
    cleared = response.headers.get_list("set-cookie")
    assert any("geekvpn_admin_access=" in header for header in cleared)
    assert any("geekvpn_admin_refresh=" in header for header in cleared)
    assert all('Max-Age=0' in header or 'expires=' in header.lower() for header in cleared)
