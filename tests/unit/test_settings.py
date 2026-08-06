"""Configuration is the most common source of production incidents.

These tests lock down the parts that are easy to get wrong: nested env parsing,
secret masking, and the production guardrails.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from geekvpn.infrastructure.config.settings import (
    Environment,
    PostgresSettings,
    RedisSettings,
    SecuritySettings,
    Settings,
    get_settings,
)

pytestmark = pytest.mark.unit


def test_nested_env_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES__HOST", "db.internal")
    monkeypatch.setenv("POSTGRES__PORT", "6543")
    monkeypatch.setenv("LOGGING__LEVEL", "debug")

    settings = Settings()

    assert settings.postgres.host == "db.internal"
    assert settings.postgres.port == 6543
    assert settings.logging.level == "DEBUG"


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGGING__LEVEL", "chatty")
    with pytest.raises(ValidationError):
        Settings()


def test_postgres_dsn_and_masked_dsn() -> None:
    pg = PostgresSettings(host="h", port=1, user="u", db="d")
    pg = pg.model_copy(update={"password": pg.password})

    assert pg.dsn().startswith("postgresql+asyncpg://u:")
    assert "***" in pg.safe_dsn
    assert pg.password.get_secret_value() not in pg.safe_dsn


def test_secret_is_not_leaked_by_repr() -> None:
    settings = SecuritySettings(secret_key="super-secret")  # type: ignore[arg-type]
    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings.secret_key)


def test_redis_dsn_without_password() -> None:
    assert RedisSettings(host="r", port=6379, db=2).dsn() == "redis://r:6379/2"


def test_cors_origins_accept_comma_separated_string() -> None:
    security = SecuritySettings(cors_origins="https://a.ir, https://b.ir")  # type: ignore[arg-type]
    assert security.cors_origins == ("https://a.ir", "https://b.ir")


def test_production_rejects_insecure_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP__ENV", "production")
    monkeypatch.setenv("APP__DEBUG", "true")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "APP__DEBUG" in str(exc_info.value)


def test_production_accepts_a_hardened_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP__ENV", "production")
    monkeypatch.setenv("APP__DEBUG", "false")
    monkeypatch.setenv("LOGGING__JSON", "true")
    monkeypatch.setenv("SECURITY__SECRET_KEY", "0" * 32)
    # Must differ from the secret key, or the guardrail refuses to boot.
    monkeypatch.setenv("SECURITY__ENCRYPTION_MASTER_KEY", "1" * 32)
    monkeypatch.setenv("POSTGRES__PASSWORD", "a-real-password")
    monkeypatch.setenv("TELEGRAM__BOT_TOKEN", "123456:AAHtesttokenfortestingonly")
    monkeypatch.setenv("TELEGRAM__WEBHOOK_SECRET", "w" * 32)

    settings = Settings()

    assert settings.app.env is Environment.PRODUCTION
    assert settings.app.env.is_deployed is True


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
