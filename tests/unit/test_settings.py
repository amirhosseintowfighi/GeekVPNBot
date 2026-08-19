"""Configuration is the most common source of production incidents.

These tests lock down the parts that are easy to get wrong: nested env parsing,
secret masking, and the production guardrails.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from geekvpn.infrastructure.config.settings import (
    INSECURE_SECRET_PREFIX,
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


def _harden(monkeypatch: pytest.MonkeyPatch) -> None:
    """The minimum a deployed environment needs, so a test can break one thing."""
    monkeypatch.setenv("APP__ENV", "production")
    monkeypatch.setenv("APP__DEBUG", "false")
    monkeypatch.setenv("LOGGING__JSON", "true")
    monkeypatch.setenv("SECURITY__SECRET_KEY", "0" * 32)
    monkeypatch.setenv("SECURITY__ENCRYPTION_MASTER_KEY", "1" * 32)
    monkeypatch.setenv("POSTGRES__PASSWORD", "a-real-password")
    monkeypatch.setenv("TELEGRAM__BOT_TOKEN", "123456:AAHtesttokenfortestingonly")
    monkeypatch.setenv("TELEGRAM__WEBHOOK_SECRET", "w" * 32)


def test_production_refuses_the_jwt_key_shipped_in_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The placeholder was long enough to pass the length check and different
    enough from SECURITY__SECRET_KEY to pass that one, so an operator who
    copied .env.example and set only the two obvious secrets shipped a
    production deployment signing tokens with a key from a public repository."""
    _harden(monkeypatch)
    monkeypatch.setenv("AUTH__JWT_SECRET_KEY", f"{INSECURE_SECRET_PREFIX}-do-not-use-in-production")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "AUTH__JWT_SECRET_KEY" in str(exc_info.value)


def test_production_accepts_a_real_jwt_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _harden(monkeypatch)
    monkeypatch.setenv("AUTH__JWT_SECRET_KEY", "2" * 48)

    assert Settings().jwt_secret == "2" * 48


def test_the_env_example_file_boots_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` is the file every operator copies, and it could not be
    loaded at all: pydantic-settings JSON-decodes a complex field straight from
    the environment, before any `mode="before"` validator runs, so
    `SECURITY__CORS_ORIGINS=http://localhost:3000` raised at the source.
    """
    for name in list(os.environ):
        # The ambient test environment must not mask a value the file sets.
        if "__" in name:
            monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=".env.example")  # type: ignore[call-arg]

    assert settings.security.cors_origins
    assert all(origin.startswith("http") for origin in settings.security.cors_origins)


def test_comma_separated_lists_survive_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The three fields an operator is told, in .env.example, to write as a
    comma-separated list."""
    monkeypatch.setenv("SECURITY__CORS_ORIGINS", "https://a.ir,https://b.ir")
    monkeypatch.setenv("AUTH__ADMIN_IP_ALLOWLIST", "10.0.0.0/24, 203.0.113.9")
    monkeypatch.setenv("SECURITY__ENCRYPTION_RETIRED_KEY_IDS", "k0,k1")

    settings = Settings()

    assert settings.security.cors_origins == ("https://a.ir", "https://b.ir")
    assert settings.auth.admin_ip_allowlist == ("10.0.0.0/24", "203.0.113.9")
    assert settings.security.encryption_retired_key_ids == ("k0", "k1")
