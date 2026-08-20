"""The admin session cookie must be one a browser will actually keep and send back."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response

from geekvpn.presentation.api.routers.admin_auth import _set_session_cookies
from geekvpn.presentation.api.schemas_auth import TokenResponse


def _tokens() -> TokenResponse:
    now = datetime.now(UTC)
    return TokenResponse(
        access_token="access-token-value",
        refresh_token="refresh-token-value",
        access_expires_at=now + timedelta(minutes=15),
        refresh_expires_at=now + timedelta(hours=12),
        session_id=uuid.uuid4(),
    )


def _headers() -> list[str]:
    response = Response()
    _set_session_cookies(response, _tokens())
    return response.headers.getlist("set-cookie")


def test_login_sets_both_cookies() -> None:
    headers = _headers()

    assert any(header.startswith("geekvpn_admin_access=") for header in headers)
    assert any(header.startswith("geekvpn_admin_refresh=") for header in headers)


def test_the_session_cookie_is_unreadable_from_javascript() -> None:
    """The panel's client holds no token by design; an XSS must not find one."""
    for header in _headers():
        assert "HttpOnly" in header


def test_the_session_cookie_never_travels_in_clear_text() -> None:
    for header in _headers():
        assert "Secure" in header


def test_a_cross_site_request_does_not_carry_the_session() -> None:
    """SameSite=Strict is what stands in for a CSRF token on these endpoints."""
    for header in _headers():
        assert "SameSite=strict" in header


def test_the_cookie_is_scoped_to_the_api_rather_than_the_whole_origin() -> None:
    """The Next.js app on the same host has no business receiving it."""
    for header in _headers():
        assert "Path=/api/" in header


def test_the_access_cookie_expires_with_its_token() -> None:
    """A cookie outliving its token means a browser that keeps sending a dead one."""
    access = next(h for h in _headers() if h.startswith("geekvpn_admin_access="))

    max_age = int(access.split("Max-Age=")[1].split(";")[0])
    assert 0 < max_age <= 15 * 60
