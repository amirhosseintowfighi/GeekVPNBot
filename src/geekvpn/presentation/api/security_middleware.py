"""HTTP-level security: response headers, CSRF enforcement, rate limiting.

Ordering matters and is not arbitrary. Starlette applies middleware in reverse
registration order, so the registration in ``app.py`` is written so that at
request time the sequence is:

    correlation id -> access log -> security headers -> rate limit -> CSRF -> route

Rate limiting sits *before* CSRF deliberately: rejecting a flood should not
require signature verification work first. Both sit after the correlation id so
that a refusal is still traceable in the logs - a 429 with no correlation id is
an incident you cannot investigate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from geekvpn.infrastructure.security import csrf
from geekvpn.infrastructure.security.ip_allowlist import (
    DENIED_MESSAGE_FA as IP_DENIED_FA,
)
from geekvpn.infrastructure.security.ip_allowlist import IpAllowlist, client_ip
from geekvpn.infrastructure.security.throttling import (
    RETRY_MESSAGE_FA,
    Decision,
    Policy,
    UnknownPolicyError,
    policy_for,
)
from geekvpn.presentation.api.errors import problem_response

logger = logging.getLogger(__name__)

RequestHandler = Callable[[Request], Awaitable[Response]]

#: Paths that must answer even when everything else is refusing traffic.
#: A readiness probe that gets rate-limited takes the pod out of service, which
#: converts a traffic spike into an outage.
EXEMPT_PATHS: Final = frozenset({"/health/live", "/health/ready", "/metrics"})

#: A strict policy is possible because both front-ends are Next.js applications
#: served from their own origins, and this API returns only JSON. An API that
#: renders no HTML has no legitimate need for scripts, frames or objects at all.
#: ``frame-ancestors 'none'`` is what actually prevents clickjacking;
#: ``X-Frame-Options`` is kept alongside it only for older browsers.
CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)

#: Applied to the interactive documentation instead, which does need to load its
#: own bundle. Kept separate rather than loosening the global policy, because a
#: policy relaxed for one page is relaxed everywhere.
DOCS_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "frame-ancestors 'none'"
)

STATIC_HEADERS: Final[dict[str, str]] = {
    # Stops a browser from guessing that a JSON error page is HTML and running
    # it, which is the mechanism behind several JSON-based XSS tricks.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Without this, a Telegram id or payment id in a URL leaks to every external
    # site the operator navigates to next.
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    # Legacy header, kept because it costs nothing and some corporate proxies
    # still honour it.
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}

#: Two years, with subdomains. Only ever sent when deployed over TLS: sending
#: HSTS from a development server over plain HTTP is how a developer's browser
#: ends up permanently refusing to load localhost.
HSTS_VALUE: Final = "max-age=63072000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defence-in-depth response headers."""

    def __init__(self, app: ASGIApp, *, deployed: bool, docs_paths: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self._deployed = deployed
        self._docs_paths = docs_paths

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        response = await call_next(request)
        for header, value in STATIC_HEADERS.items():
            # setdefault, not assignment: a route that deliberately set its own
            # value (a download with a different CORP, say) must win.
            response.headers.setdefault(header, value)

        path = request.url.path
        is_docs = any(path.startswith(prefix) for prefix in self._docs_paths)
        response.headers.setdefault(
            "Content-Security-Policy",
            DOCS_CONTENT_SECURITY_POLICY if is_docs else CONTENT_SECURITY_POLICY,
        )
        if self._deployed:
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        return response


class CsrfMiddleware(BaseHTTPMiddleware):
    """Enforces double-submit CSRF on cookie-authenticated state changes.

    Scoped to the paths that read the refresh cookie. Everything else in this API
    authenticates with a Bearer header and is not forgeable cross-site; see the
    module docstring in ``infrastructure/security/csrf.py``.
    """

    def __init__(self, app: ASGIApp, *, secret: str, protected_prefixes: tuple[str, ...]) -> None:
        super().__init__(app)
        self._secret = secret
        self._protected_prefixes = protected_prefixes

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in self._protected_prefixes):
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        verdict = csrf.check_request(
            self._secret,
            method=request.method,
            cookie_token=request.cookies.get(csrf.COOKIE_NAME),
            header_token=request.headers.get(csrf.HEADER_NAME),
            # The session is identified by the refresh cookie itself. A token
            # bound to the presented cookie cannot be replayed against another.
            session_id=request.cookies.get(csrf.REFRESH_COOKIE_NAME, "")[:64],
            has_bearer_token=authorization.lower().startswith("bearer "),
        )
        if verdict.ok:
            return await call_next(request)

        logger.warning(
            "csrf.rejected",
            extra={"path": path, "reason": verdict.reason, "method": request.method},
        )
        return problem_response(
            status_code=403,
            title="CSRF validation failed",
            detail=csrf.DENIED_MESSAGE_FA,
            instance=path,
            extra={"reason": verdict.reason},
        )


class SlidingWindowLimiter(Protocol):
    """What this middleware needs from a limiter.

    Structural, so both `RedisSlidingWindowLimiter` and the proxy in `app.py`
    that resolves it from the container at request time satisfy it without
    either importing the other.
    """

    async def check(
        self, policy: Policy, *, subject_id: str | None, ip: str | None
    ) -> Decision: ...


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies a named policy to each request and advertises the headroom.

    Policies are chosen by prefix rather than by exact route, and the table is
    explicit: a path with no entry is **not** limited here. That is intentional -
    per-route limits that matter (login failures, checkout) are applied inside
    the endpoints, where the limiter can distinguish a failed attempt from a
    successful one. This middleware is the coarse net that stops a flood before
    it reaches a database session.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: SlidingWindowLimiter,
        route_policies: tuple[tuple[str, str], ...],
        trusted_proxy_count: int = 0,
        default_policy: str | None = None,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._route_policies = route_policies
        self._trusted_proxy_count = trusted_proxy_count
        self._default_policy = default_policy

    def _policy_name(self, path: str) -> str | None:
        # Longest prefix wins, so "/api/v1/admin/analytics/export" is not caught
        # by the looser "/api/v1/admin" entry.
        best: tuple[int, str] | None = None
        for prefix, name in self._route_policies:
            if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), name)
        return best[1] if best else self._default_policy

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)

        name = self._policy_name(path)
        if name is None:
            return await call_next(request)
        try:
            policy = policy_for(name)
        except UnknownPolicyError:
            # A missing policy must be loud but must not take the API down.
            logger.error("ratelimit.unknown_policy", extra={"policy": name, "path": path})
            return await call_next(request)

        address = client_ip(
            remote_addr=request.client.host if request.client else None,
            forwarded_for=request.headers.get("X-Forwarded-For"),
            real_ip=request.headers.get("X-Real-IP"),
            trusted_proxy_count=self._trusted_proxy_count,
        )
        subject = getattr(request.state, "subject_id", None)
        decision = await self._limiter.check(policy, subject_id=subject, ip=address)

        if not decision.allowed:
            logger.info(
                "ratelimit.refused",
                extra={
                    "policy": policy.name,
                    "path": path,
                    "retry_after": decision.retry_after_seconds,
                },
            )
            return problem_response(
                status_code=429,
                title="Too Many Requests",
                detail=RETRY_MESSAGE_FA.format(seconds=decision.retry_after_seconds),
                instance=path,
                headers=decision.headers(),
            )

        response = await call_next(request)
        for header, value in decision.headers().items():
            response.headers.setdefault(header, value)
        return response


class AdminIpAllowlistMiddleware(BaseHTTPMiddleware):
    """Restricts the admin surface to approved networks.

    Honours the ``AuthSettings.admin_ip_allowlist`` setting that already existed
    but was never enforced anywhere. An unenforced allowlist in a settings file
    is worse than none: it reads like a control during a review.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowlist: IpAllowlist,
        protected_prefixes: tuple[str, ...],
        trusted_proxy_count: int = 0,
    ) -> None:
        super().__init__(app)
        self._allowlist = allowlist
        self._protected_prefixes = protected_prefixes
        self._trusted_proxy_count = trusted_proxy_count

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if self._allowlist.is_empty:
            return await call_next(request)
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in self._protected_prefixes):
            return await call_next(request)

        address = client_ip(
            remote_addr=request.client.host if request.client else None,
            forwarded_for=request.headers.get("X-Forwarded-For"),
            real_ip=request.headers.get("X-Real-IP"),
            trusted_proxy_count=self._trusted_proxy_count,
        )
        if self._allowlist.allows(address):
            return await call_next(request)

        logger.warning("admin.ip_refused", extra={"path": path, "ip": address})
        # 404, not 403: confirming that an admin API exists at this path to an
        # unapproved network is free reconnaissance.
        return problem_response(
            status_code=404,
            title="Not Found",
            detail=IP_DENIED_FA,
            instance=path,
        )


#: Coarse per-prefix limits for the middleware. Ordered loosest to tightest for
#: readability only; the lookup picks the longest matching prefix.
DEFAULT_ROUTE_POLICIES: Final[tuple[tuple[str, str], ...]] = (
    ("/api/v1/catalog", "catalog.browse"),
    ("/api/v1/miniapp", "miniapp.read"),
    ("/api/v1/auth/refresh", "auth.refresh"),
    ("/api/v1/auth/telegram", "auth.telegram"),
    ("/api/v1/auth/captcha", "auth.captcha"),
    ("/api/v1/admin/analytics/export", "analytics.export"),
    ("/api/v1/admin/analytics", "analytics.dashboard"),
    ("/api/v1/admin/broadcasts", "admin.broadcast"),
    ("/api/v1/admin", "admin.mutation"),
    ("/api/v1/payments/receipt", "payments.receipt"),
    ("/api/v1/payments", "payments.checkout"),
    ("/api/v1/wallet", "wallet.read"),
    ("/api/v1/support/search", "support.search"),
    ("/api/v1/support/tickets", "support.open_ticket"),
)

__all__ = [
    "CONTENT_SECURITY_POLICY",
    "DEFAULT_ROUTE_POLICIES",
    "DOCS_CONTENT_SECURITY_POLICY",
    "EXEMPT_PATHS",
    "HSTS_VALUE",
    "STATIC_HEADERS",
    "AdminIpAllowlistMiddleware",
    "CsrfMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
]
