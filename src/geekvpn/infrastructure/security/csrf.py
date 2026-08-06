"""CSRF protection for the one endpoint that actually needs it.

An honest scope, because over-claiming here is common
-----------------------------------------------------
The admin panel and Mini App authenticate with ``Authorization: Bearer`` headers
(see ``presentation/api/security.py``). A cross-site request **cannot** set that
header, so those endpoints are not vulnerable to CSRF and adding tokens to them
would be ceremony. Claiming otherwise in a security report is how a review ends
up satisfied with a control that protects nothing.

The genuinely exposed surface is the refresh endpoint, because a refresh token
lives in a cookie and cookies *are* sent cross-site. Without protection, a page
the operator visits can silently mint a fresh access token pair. So:

* the cookie is ``HttpOnly`` (JavaScript cannot read it), ``Secure`` in deployed
  environments, and ``SameSite=Lax``;
* plus a double-submit token, because ``SameSite`` alone is browser-dependent
  and a same-site subdomain that an attacker controls defeats ``Lax``.

The token is HMAC-signed and bound to the session, so it cannot be forged and a
token lifted from one session is useless in another. It is stateless - no Redis
round-trip on the hot path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Final

COOKIE_NAME: Final = "geekvpn_csrf"
HEADER_NAME: Final = "X-CSRF-Token"
REFRESH_COOKIE_NAME: Final = "geekvpn_refresh"

#: Methods that cannot change state and therefore need no token. HEAD and
#: OPTIONS are included; OPTIONS especially, since demanding a token on the
#: preflight breaks every browser client.
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

_NONCE_BYTES: Final = 16
_SEPARATOR: Final = "."
_INFO: Final = b"geekvpn/csrf/v1"


class CsrfError(Exception):
    """The request failed CSRF validation."""


def _sign(secret: str, *, nonce: str, session_id: str) -> str:
    message = f"{nonce}|{session_id}".encode()
    key = hashlib.sha256(_INFO + secret.encode("utf-8")).digest()
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_token(secret: str, *, session_id: str) -> str:
    """Mint a token bound to one session. Format: ``<nonce>.<signature>``."""
    if not secret or len(secret) < 32:
        # The same floor the JWT service uses. A short key here would make the
        # signature forgeable, and a forgeable CSRF token is no CSRF token.
        raise CsrfError("CSRF signing secret must be at least 32 characters.")
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(_NONCE_BYTES)).decode("ascii").rstrip("=")
    return f"{nonce}{_SEPARATOR}{_sign(secret, nonce=nonce, session_id=session_id)}"


def verify_token(secret: str, token: str | None, *, session_id: str) -> bool:
    """Whether a token is authentic and belongs to this session."""
    if not token or _SEPARATOR not in token:
        return False
    nonce, _, signature = token.partition(_SEPARATOR)
    if not nonce or not signature:
        return False
    expected = _sign(secret, nonce=nonce, session_id=session_id)
    # Constant-time: a timing-comparable check leaks the signature byte by byte.
    return hmac.compare_digest(signature, expected)


@dataclass(frozen=True, slots=True)
class CsrfVerdict:
    ok: bool
    reason: str = ""


def check_request(
    secret: str,
    *,
    method: str,
    cookie_token: str | None,
    header_token: str | None,
    session_id: str,
    has_bearer_token: bool = False,
) -> CsrfVerdict:
    """The full double-submit check.

    Both halves must be present, must match each other, and must carry a valid
    signature for this session. Matching alone is not enough: an attacker who can
    set a cookie could otherwise write the same value into both places.
    """
    if method.upper() in SAFE_METHODS:
        return CsrfVerdict(True, "safe method")
    if has_bearer_token:
        # A cross-site page cannot set an Authorization header, so this request
        # is not forgeable and demanding a token would break API clients.
        return CsrfVerdict(True, "bearer authenticated")
    if not cookie_token or not header_token:
        return CsrfVerdict(False, "missing token")
    if not hmac.compare_digest(cookie_token, header_token):
        return CsrfVerdict(False, "token mismatch")
    if not verify_token(secret, header_token, session_id=session_id):
        return CsrfVerdict(False, "bad signature")
    return CsrfVerdict(True, "verified")


def cookie_settings(*, deployed: bool) -> dict[str, object]:
    """Attributes for the CSRF cookie.

    ``httponly`` is **false** here, and only here: the browser must read this one
    to echo it in the header. That is safe because the value is worthless without
    the session it is bound to. The refresh cookie is the opposite.
    """
    return {
        "httponly": False,
        "secure": deployed,
        "samesite": "lax",
        "path": "/",
    }


def refresh_cookie_settings(*, deployed: bool, max_age_seconds: int) -> dict[str, object]:
    """Attributes for the refresh-token cookie.

    ``secure`` is tied to whether the environment is deployed rather than being
    hard-coded true, because local development over plain HTTP would otherwise
    silently drop the cookie and appear to be a broken login.
    """
    return {
        "httponly": True,
        "secure": deployed,
        "samesite": "lax",
        "path": "/api/v1/auth",
        "max_age": max_age_seconds,
    }


DENIED_MESSAGE_FA: Final = (
    "درخواست معتبر نیست. لطفاً صفحه را دوباره بارگزاری کنید و دوباره تلاش کنید."
)

__all__ = [
    "COOKIE_NAME",
    "DENIED_MESSAGE_FA",
    "HEADER_NAME",
    "REFRESH_COOKIE_NAME",
    "SAFE_METHODS",
    "CsrfError",
    "CsrfVerdict",
    "check_request",
    "cookie_settings",
    "issue_token",
    "refresh_cookie_settings",
    "verify_token",
]
