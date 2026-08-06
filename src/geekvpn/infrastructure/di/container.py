"""Composition root.

This is the only module that knows how to build concrete adapters. Everything
else receives what it needs as an argument.

Why a hand-written container instead of a DI framework:
* it is readable by anyone on day one and fully typed;
* construction order is explicit, so startup failures are obvious;
* tests build a container with fakes without any framework-specific override
  machinery.

Two scopes exist, and the distinction matters:
* the **container** holds process-wide, stateless or pooled objects;
* a **RequestScope** (see `scope.py`) holds everything bound to one database
  session - repositories, the audit recorder, use cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from geekvpn.application.identity.session_service import SessionPolicy
from geekvpn.application.ports.health import HealthProbe
from geekvpn.infrastructure.cache.redis import RedisCache, create_redis
from geekvpn.infrastructure.cache.report_cache import RedisReportCache
from geekvpn.infrastructure.clock import SystemClock
from geekvpn.infrastructure.config.settings import Settings
from geekvpn.infrastructure.health.probes import DatabaseProbe, RedisProbe
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.persistence.engine import (
    create_engine,
    create_reporting_engine,
    create_session_factory,
    create_sync_session_factory,
    create_write_sync_engine,
)
from geekvpn.infrastructure.persistence.types import install_keyring
from geekvpn.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from geekvpn.infrastructure.security.captcha_store import RedisCaptchaStore
from geekvpn.infrastructure.security.crypto import KeyRing
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService
from geekvpn.infrastructure.security.passwords import Argon2Hasher
from geekvpn.infrastructure.security.rate_limit import RedisRateLimiter
from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory
from geekvpn.infrastructure.security.revocation import RedisRevocationList
from geekvpn.infrastructure.security.sliding_window import RedisSlidingWindowLimiter
from geekvpn.infrastructure.security.telegram import TelegramSignatureVerifier
from geekvpn.infrastructure.security.totp import Rfc6238TotpService

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class Container:
    """Long-lived, process-wide dependencies.

    Request-scoped objects (sessions, units of work, repositories) are created
    *from* the container, never stored on it.
    """

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    #: Separate synchronous pool, used only by analytics reporting.
    reporting_engine: Engine
    reporting_sessions: sessionmaker[Session]
    #: Synchronous write pool, used by the synchronous payment, support
    #: and notification services (see ``di/sync_scope.py``).
    sync_engine: Engine
    sync_sessions: sessionmaker[Session]
    redis: Redis
    cache: RedisCache
    clock: SystemClock
    health_probes: tuple[HealthProbe, ...]

    # Security services: stateless and safe to share across requests.
    access_tokens: JwtAccessTokenService
    refresh_tokens: Sha256RefreshTokenFactory
    passwords: Argon2Hasher
    totp: Rfc6238TotpService
    telegram_auth: TelegramSignatureVerifier | None
    #: Fixed-window limiter, kept for the existing callers that use the
    #: ``RateLimiter`` port directly.
    rate_limiter: RedisRateLimiter
    #: Sliding-window limiter used by the HTTP middleware. Both exist on purpose:
    #: a fixed window lets twice the limit through at a window boundary, which is
    #: tolerable for a browse endpoint and not for a login endpoint.
    sliding_limiter: RedisSlidingWindowLimiter
    captcha_store: RedisCaptchaStore
    report_cache: RedisReportCache
    #: Encryption keys for data at rest. Built once at startup so a missing or
    #: too-short master key fails at boot rather than on the first card number
    #: someone tries to store.
    keyring: KeyRing
    revocations: RedisRevocationList
    user_session_policy: SessionPolicy
    admin_session_policy: SessionPolicy

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """Factory for a request-scoped transaction."""
        return SqlAlchemyUnitOfWork(self.session_factory)


def build_container(settings: Settings) -> Container:
    """Wire the object graph. Cheap and synchronous: no I/O happens here.

    Connections are established lazily on first use, which keeps startup fast
    and lets readiness - not liveness - be the thing that reports a dependency
    outage.
    """
    engine = create_engine(settings.postgres)
    session_factory = create_session_factory(engine)
    reporting_engine = create_reporting_engine(settings.postgres)
    sync_engine = create_write_sync_engine(settings.postgres)
    redis = create_redis(settings.redis)

    bot_token = settings.telegram.bot_token.get_secret_value()
    telegram_auth = (
        TelegramSignatureVerifier(
            bot_token=bot_token,
            max_age_seconds=settings.telegram.auth_max_age_seconds,
        )
        if bot_token
        else None
    )
    if telegram_auth is None:
        # Local development without a token is allowed; the production
        # guardrail in Settings makes this impossible in a deployed env.
        logger.warning("telegram.auth_disabled", reason="TELEGRAM__BOT_TOKEN is empty")

    container = Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        reporting_engine=reporting_engine,
        reporting_sessions=create_sync_session_factory(reporting_engine),
        sync_engine=sync_engine,
        sync_sessions=create_sync_session_factory(sync_engine),
        redis=redis,
        cache=RedisCache(redis, namespace=settings.app.name),
        clock=SystemClock(),
        health_probes=(DatabaseProbe(engine), RedisProbe(redis)),
        access_tokens=JwtAccessTokenService(
            secret_key=settings.jwt_secret,
            issuer=settings.auth.jwt_issuer,
            audience=settings.auth.jwt_audience,
            ttl=settings.auth.access_ttl,
        ),
        refresh_tokens=Sha256RefreshTokenFactory(),
        passwords=Argon2Hasher(),
        totp=Rfc6238TotpService(),
        telegram_auth=telegram_auth,
        rate_limiter=RedisRateLimiter(redis),
        sliding_limiter=RedisSlidingWindowLimiter(redis),
        captcha_store=RedisCaptchaStore(redis),
        report_cache=RedisReportCache(redis),
        keyring=KeyRing.from_master_secret(
            settings.security.encryption_master_key.get_secret_value(),
            active_key_id=settings.security.encryption_active_key_id,
            retired_key_ids=settings.security.encryption_retired_key_ids,
        ),
        revocations=RedisRevocationList(redis),
        user_session_policy=SessionPolicy(
            refresh_ttl=settings.auth.user_refresh_ttl,
            absolute_ttl=settings.auth.user_absolute_ttl,
        ),
        admin_session_policy=SessionPolicy(
            refresh_ttl=settings.auth.admin_refresh_ttl,
            absolute_ttl=settings.auth.admin_absolute_ttl,
        ),
    )
    # Encrypted columns resolve their keyring through this hook. It was never
    # called, which meant the very first read of an encrypted column would raise
    # EncryptionNotConfiguredError at runtime - loud, but only in production and
    # only once a node had credentials. Installing it here makes the failure a
    # boot failure instead.
    install_keyring(lambda: container.keyring)

    logger.info(
        "container.built",
        env=settings.app.env.value,
        database=settings.postgres.safe_dsn,
        redis_host=settings.redis.host,
        telegram_auth=telegram_auth is not None,
        encryption_keys=len(container.keyring.key_ids),
        active_key_id=container.keyring.active_key_id,
    )
    return container


async def close_container(container: Container) -> None:
    """Release every pooled resource. Must be idempotent-safe on shutdown paths."""
    await container.redis.aclose()
    await container.engine.dispose()
    container.reporting_engine.dispose()
    container.sync_engine.dispose()
    logger.info("container.closed")
