"""Shared fixtures.

The container is built with fake infrastructure (no Postgres, no Redis) but
**real** security adapters, so JWT signing, Telegram HMAC verification and TOTP
are exercised for real on every test run. Argon2 is the one exception: it is
deliberately expensive, so the API tests use a trivial hasher and Argon2 itself
is covered by its own unit test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.application.identity.session_service import SessionPolicy
from geekvpn.application.ports.health import ProbeResult
from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.security.crypto import KeyRing
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService
from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory
from geekvpn.infrastructure.security.telegram import TelegramSignatureVerifier
from geekvpn.infrastructure.security.totp import Rfc6238TotpService
from geekvpn.presentation.api.app import create_app
from geekvpn.presentation.bot.app import create_bot_app
from tests.fakes import (
    AllowingRateLimiter,
    FakeAsyncSession,
    FrozenClock,
    InMemoryRevocationList,
)

TEST_SECRET = "t" * 48
TEST_BOT_TOKEN = "123456:AAHtesttokenfortestingonly"


class FakeProbe:
    """Health probe that reports whatever the test needs it to report."""

    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy
        self.calls = 0

    async def check(self) -> ProbeResult:
        self.calls += 1
        return ProbeResult(
            name=self.name,
            healthy=self._healthy,
            latency_ms=0.0,
            error=None if self._healthy else "unavailable",
        )


class FakeClock:
    """Kept for Phase 1 tests that import it by name."""

    def __init__(self, moment: datetime | None = None) -> None:
        self._moment = moment or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment


class FakeCache:
    """Enough of the cache port for the TOTP replay guard and settings cache."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.items.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.items[key] = value

    async def delete(self, key: str) -> None:
        self.items.pop(key, None)

    async def add_if_absent(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        if key in self.items:
            return False
        self.items[key] = value
        return True


class FastHasher:
    """Argon2 with production parameters costs ~100ms per call."""

    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Settings are cached with lru_cache; leaking that between tests makes
    failures depend on file order, which is the worst kind of flake."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("APP__ENV", "local")
    monkeypatch.setenv("AUTH__JWT_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("TELEGRAM__BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()
    return get_settings()


def build_test_container(settings: Settings, *, healthy: bool = True) -> Container:
    return Container(
        settings=settings,
        engine=None,  # type: ignore[arg-type]
        session_factory=FakeAsyncSession,  # type: ignore[arg-type]
        reporting_engine=None,  # type: ignore[arg-type]
        reporting_sessions=None,  # type: ignore[arg-type]
        sync_engine=None,  # type: ignore[arg-type]
        sync_sessions=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        cache=FakeCache(),  # type: ignore[arg-type]
        clock=FrozenClock(),  # type: ignore[arg-type]
        health_probes=(
            FakeProbe("postgres", healthy=healthy),  # type: ignore[arg-type]
            FakeProbe("redis", healthy=healthy),  # type: ignore[arg-type]
        ),
        access_tokens=JwtAccessTokenService(
            secret_key=TEST_SECRET,
            issuer=settings.auth.jwt_issuer,
            audience=settings.auth.jwt_audience,
            ttl=timedelta(minutes=15),
        ),
        refresh_tokens=Sha256RefreshTokenFactory(),
        passwords=FastHasher(),  # type: ignore[arg-type]
        totp=Rfc6238TotpService(),
        telegram_auth=TelegramSignatureVerifier(bot_token=TEST_BOT_TOKEN),
        rate_limiter=AllowingRateLimiter(),  # type: ignore[arg-type]
        sliding_limiter=None,  # type: ignore[arg-type]
        captcha_store=None,  # type: ignore[arg-type]
        report_cache=None,  # type: ignore[arg-type]
        # A real keyring, not a fake: it needs no I/O, and a fake would hide the
        # EncryptionNotConfiguredError that an unwired keyring is meant to raise.
        keyring=KeyRing.from_master_secret(TEST_SECRET),
        revocations=InMemoryRevocationList(),  # type: ignore[arg-type]
        user_session_policy=SessionPolicy(
            refresh_ttl=timedelta(days=30), absolute_ttl=timedelta(days=180)
        ),
        admin_session_policy=SessionPolicy(
            refresh_ttl=timedelta(hours=12), absolute_ttl=timedelta(hours=24)
        ),
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_test_container(settings)


@pytest.fixture
def degraded_container(settings: Settings) -> Container:
    return build_test_container(settings, healthy=False)


@pytest.fixture
def auth_container(container: Container) -> Container:
    """Alias, so auth tests can diverge from health tests later without churn."""
    return container


@pytest.fixture
def app(container: Container) -> FastAPI:
    return create_app(container=container)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


#: Set by the shared bot app so webhook tests can sign their requests.
BOT_WEBHOOK_SECRET = "w" * 32


@pytest.fixture(scope="session")
def bot_client() -> Iterator[TestClient]:
    """The one bot application a process is allowed to run.

    Handler routers are module-level singletons and aiogram refuses to attach a
    router to a second dispatcher. The dispatcher is built by the lifespan, so
    the limit is one *entered* client per process, not merely one app - which
    is why this owns the TestClient rather than handing out the app.
    Session-scoped for that reason, not for speed.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("APP__ENV", "local")
    patch.setenv("AUTH__JWT_SECRET_KEY", TEST_SECRET)
    patch.setenv("TELEGRAM__BOT_TOKEN", TEST_BOT_TOKEN)
    patch.setenv("TELEGRAM__WEBHOOK_SECRET", BOT_WEBHOOK_SECRET)
    get_settings.cache_clear()
    settings = get_settings()

    app = create_bot_app(settings, container=build_test_container(settings))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    patch.undo()
    get_settings.cache_clear()
