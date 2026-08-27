"""FastAPI application factory.

A factory rather than a module-level ``app`` so tests can build an isolated
application with an injected container.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from geekvpn import __version__
from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.infrastructure.di.container import Container, build_container, close_container
from geekvpn.infrastructure.logging.setup import configure_logging, get_logger
from geekvpn.infrastructure.observability.metrics import AppMetrics
from geekvpn.infrastructure.security.ip_allowlist import IpAllowlist
from geekvpn.infrastructure.security.throttling import Decision, Policy
from geekvpn.presentation.api.errors import register_exception_handlers
from geekvpn.presentation.api.metrics_middleware import MetricsMiddleware, metrics_endpoint
from geekvpn.presentation.api.middleware import AccessLogMiddleware, CorrelationIdMiddleware
from geekvpn.presentation.api.routers import (
    admin_analytics,
    admin_auth,
    admin_broadcasts,
    admin_catalog,
    admin_customers,
    admin_orders,
    admin_panels,
    admin_payments,
    admin_resellers,
    admin_subscriptions,
    admin_support,
    admin_users,
    admin_wallet,
    auth,
    catalog,
    gateway_callback,
    health,
    meta,
    miniapp,
    reseller,
    reseller_applications,
)
from geekvpn.presentation.api.routers import (
    settings as settings_router,
)
from geekvpn.presentation.api.security_middleware import (
    DEFAULT_ROUTE_POLICIES,
    AdminIpAllowlistMiddleware,
    CsrfMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = get_logger(__name__)

API_V1_PREFIX = "/api/v1"


class _LimiterProxy:
    """Resolves the limiter from the app's container at request time.

    Middleware is constructed before the lifespan runs, so the container does not
    exist yet. Holding the app and reading the limiter per request is what lets
    the middleware be registered at import time.

    When no limiter is present the verdict is "allowed". That is the fail-open
    posture documented in ``docs/security.md``, and it is only defensible because
    the strong control - consecutive-failure lockout - is counted in Postgres.
    """

    __slots__ = ("_app",)

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def check(self, policy: Policy, *, subject_id: str | None, ip: str | None) -> Decision:
        container = getattr(self._app.state, "container", None)
        limiter = getattr(container, "sliding_limiter", None)
        if limiter is None:
            return Decision(
                allowed=True,
                policy_name=policy.name,
                limit=policy.limit,
                remaining=policy.limit,
                retry_after_seconds=0,
            )
        decision: Decision = await limiter.check(policy, subject_id=subject_id, ip=ip)
        return decision


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
) -> FastAPI:
    """Build the API application.

    :param settings: overrides the environment-derived settings (tests).
    :param container: pre-built dependency container (tests). When provided,
        the application will not close it on shutdown - whoever built it owns it.
    """
    settings = settings or get_settings()
    configure_logging(
        level=settings.logging.level,
        json_output=settings.logging.json,
        redact_keys=settings.logging.redact_keys,
        service=f"{settings.app.name}-api",
    )

    externally_owned_container = container is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        app.state.settings = settings
        logger.info("api.startup", env=settings.app.env.value, version=app.version)
        try:
            yield
        finally:
            if not externally_owned_container:
                await close_container(app.state.container)
            logger.info("api.shutdown")

    app = FastAPI(
        title="Geek VPN API",
        version=__version__,
        description=(
            "Core API for the Geek VPN platform. The Telegram bot, the Mini App, "
            "the admin panel and any future client are thin clients over this API."
        ),
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        docs_url=f"{API_V1_PREFIX}/docs" if not settings.app.env.is_deployed else None,
        redoc_url=f"{API_V1_PREFIX}/redoc" if not settings.app.env.is_deployed else None,
        lifespan=lifespan,
        debug=settings.app.debug,
    )

    app.state.metrics = AppMetrics.create()
    app.state.metrics.build_info.set(1, version=app.version, environment=settings.app.env.value)

    # Starlette applies middleware in reverse registration order, so this block
    # is written bottom-up. A request travels:
    #   metrics -> correlation id -> access log -> security headers
    #   -> admin allowlist -> rate limit -> CSRF -> route
    # Correlation id must precede the access log so every line carries it, and
    # the rate limiter must precede routing so a refused request never reaches a
    # database session.
    app.add_middleware(
        CsrfMiddleware,
        secret=settings.jwt_secret,
        protected_prefixes=(
            f"{API_V1_PREFIX}/auth/refresh",
            f"{API_V1_PREFIX}/auth/logout",
        ),
    )
    app.add_middleware(
        RateLimitMiddleware,
        limiter=_LimiterProxy(app),
        route_policies=DEFAULT_ROUTE_POLICIES,
        trusted_proxy_count=settings.security.trusted_proxy_count,
    )
    admin_allowlist = IpAllowlist.from_entries(settings.auth.admin_ip_allowlist)
    if not admin_allowlist.is_empty:
        # Registered only when configured. An empty allowlist that silently
        # allowed everything would look identical to a working one.
        app.add_middleware(
            AdminIpAllowlistMiddleware,
            allowlist=admin_allowlist,
            protected_prefixes=(f"{API_V1_PREFIX}/admin",),
            trusted_proxy_count=settings.security.trusted_proxy_count,
        )
    app.add_middleware(SecurityHeadersMiddleware, deployed=settings.app.env.is_deployed)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(MetricsMiddleware, metrics=app.state.metrics)
    if settings.security.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.security.cors_origins),
            allow_credentials=True,
            allow_methods=list(settings.security.cors_allow_methods),
            allow_headers=list(settings.security.cors_allow_headers),
            expose_headers=["X-Correlation-Id", "Retry-After", "X-RateLimit-Remaining"],
            max_age=600,
        )

    register_exception_handlers(app)

    # Scrape endpoint. Added as a plain route rather than a router because it
    # must not carry the /api/v1 prefix or appear in the public OpenAPI schema.
    # Nginx denies it at the edge; Prometheus reaches it over the internal network.
    app.add_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    app.include_router(health.router)
    app.include_router(meta.router, prefix=API_V1_PREFIX)
    app.include_router(auth.router, prefix=API_V1_PREFIX)
    app.include_router(admin_auth.router, prefix=API_V1_PREFIX)
    app.include_router(admin_users.router, prefix=API_V1_PREFIX)
    app.include_router(catalog.router, prefix=API_V1_PREFIX)
    app.include_router(admin_catalog.router, prefix=API_V1_PREFIX)
    app.include_router(admin_catalog.ladder_router, prefix=API_V1_PREFIX)
    app.include_router(settings_router.router, prefix=API_V1_PREFIX)
    app.include_router(admin_analytics.router, prefix=API_V1_PREFIX)
    app.include_router(admin_payments.router, prefix=API_V1_PREFIX)
    app.include_router(admin_support.router, prefix=API_V1_PREFIX)
    app.include_router(admin_support.templates_router, prefix=API_V1_PREFIX)
    app.include_router(admin_wallet.router, prefix=API_V1_PREFIX)
    app.include_router(admin_panels.router, prefix=API_V1_PREFIX)
    app.include_router(admin_orders.router, prefix=API_V1_PREFIX)
    app.include_router(admin_subscriptions.router, prefix=API_V1_PREFIX)
    app.include_router(admin_customers.router, prefix=API_V1_PREFIX)
    app.include_router(admin_broadcasts.router, prefix=API_V1_PREFIX)
    app.include_router(admin_resellers.router, prefix=API_V1_PREFIX)
    app.include_router(reseller.router, prefix=API_V1_PREFIX)
    app.include_router(reseller_applications.router, prefix=API_V1_PREFIX)
    # Unauthenticated on purpose: somebody redeeming a first-password link has
    # no way to get a session yet, which is why the link exists.
    app.include_router(reseller_applications.public_router, prefix=API_V1_PREFIX)
    # Unauthenticated and unversioned: a customer arrives here in a browser
    # redirected by a bank, carrying no session - and the URL was handed to the
    # provider when the payment started, so it must not move between versions.
    app.include_router(gateway_callback.router)
    # No API_V1_PREFIX: the Mini App calls /api/miniapp/* and its own router
    # already carries that prefix.
    app.include_router(miniapp.router)

    return app
