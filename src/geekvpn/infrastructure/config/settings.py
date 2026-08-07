"""Typed, validated configuration.

Rules:
* Configuration comes from the environment only. No config files, no defaults
  that are unsafe in production.
* Secrets are ``SecretStr`` so they cannot be logged by accident.
* Nested sections use a double underscore: ``POSTGRES__PASSWORD``.
* ``get_settings()`` is cached: settings are read once per process.
"""

from __future__ import annotations

import enum
from datetime import timedelta
from functools import lru_cache

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Any secret that still equals this is a configuration error in production.
INSECURE_SECRET_PREFIX = "insecure-development-key"  # noqa: S105 - a constant name, not a credential
_DEV_SECRET = "insecure-development-key-do-not-use-in-production"  # noqa: S105 - a constant name, not a credential


class Environment(str, enum.Enum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_deployed(self) -> bool:
        return self is not Environment.LOCAL


class AppSettings(BaseSettings):
    name: str = "geekvpn"
    env: Environment = Environment.LOCAL
    debug: bool = False
    base_url: str = "http://localhost:8000"
    request_timeout_seconds: float = 30.0


class LoggingSettings(BaseSettings):
    level: str = "INFO"
    #: Shadows the deprecated `BaseModel.json` method. Kept because the name
    #: is the documented `LOGGING__JSON` environment variable, and renaming
    #: the field would silently ignore every existing deployment's setting.
    json: bool = True  # type: ignore[assignment]
    # Values never written to logs, whatever the key path.
    redact_keys: tuple[str, ...] = (
        "password",
        "token",
        "secret",
        "authorization",
        "api_key",
        "init_data",
        "refresh_token",
        "access_token",
        "totp_code",
        "totp_secret",
    )

    @field_validator("level")
    @classmethod
    def _upper(cls, value: str) -> str:
        level = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"level must be one of {sorted(allowed)}")
        return level


class PostgresSettings(BaseSettings):
    host: str = "postgres"
    port: int = 5432
    user: str = "geekvpn"
    password: SecretStr = SecretStr("geekvpn")
    db: str = "geekvpn"
    pool_size: int = 10
    max_overflow: int = 10
    pool_timeout_seconds: int = 10
    pool_recycle_seconds: int = 1800
    echo: bool = False

    def dsn(self, *, driver: str = "postgresql+asyncpg") -> str:
        pwd = self.password.get_secret_value()
        return f"{driver}://{self.user}:{pwd}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def safe_dsn(self) -> str:
        """DSN with the password masked - safe to log."""
        return f"postgresql+asyncpg://{self.user}:***@{self.host}:{self.port}/{self.db}"


class RedisSettings(BaseSettings):
    host: str = "redis"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None
    socket_timeout_seconds: float = 5.0
    max_connections: int = 50

    def dsn(self) -> str:
        auth = f":{self.password.get_secret_value()}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class TelegramSettings(BaseSettings):
    bot_token: SecretStr = SecretStr("")
    webhook_base_url: str = ""
    webhook_path: str = "/telegram/webhook"
    webhook_secret: SecretStr = SecretStr("")
    set_webhook_on_startup: bool = False
    parse_mode: str = "HTML"
    #: How old signed Telegram auth data may be before it is rejected.
    auth_max_age_seconds: int = 86_400

    @computed_field  # type: ignore[prop-decorator]
    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url.rstrip('/')}{self.webhook_path}"


class SecuritySettings(BaseSettings):
    secret_key: SecretStr = SecretStr(_DEV_SECRET)
    cors_origins: tuple[str, ...] = ()

    #: Master secret for data encrypted at rest. Deliberately separate from
    #: ``secret_key``: sharing one secret would couple the two rotations
    #: permanently, so the JWT key could never be rotated without re-encrypting
    #: every stored card number.
    encryption_master_key: SecretStr = SecretStr(_DEV_SECRET)
    encryption_active_key_id: str = "k1"
    #: Keys that must still decrypt but must no longer encrypt, during rotation.
    encryption_retired_key_ids: tuple[str, ...] = ()

    #: Number of reverse proxies in front of the application. Used to read
    #: ``X-Forwarded-For`` from the right, so a client-supplied leftmost entry
    #: cannot impersonate an allowlisted address. Zero means "trust no
    #: forwarding header at all", which is correct when there is no proxy.
    trusted_proxy_count: int = 0

    #: Explicit CORS lists rather than a wildcard. A wildcard method list also
    #: permits methods the API does not implement, which is free reconnaissance.
    cors_allow_methods: tuple[str, ...] = ("GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS")
    cors_allow_headers: tuple[str, ...] = (
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-CSRF-Token",
        "X-Device-Label",
        "X-Correlation-Id",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator(
        "encryption_retired_key_ids",
        "cors_allow_methods",
        "cors_allow_headers",
        mode="before",
    )
    @classmethod
    def _split_tuple(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value


class AuthSettings(BaseSettings):
    """Token lifetimes and admin login hardening.

    Defaults encode a deliberate position:

    * a 15-minute access token bounds the damage of a leaked token while
      keeping the database out of the request path;
    * customers get a 30-day refresh window because forcing a re-login to
      check remaining traffic is hostile;
    * admins get 12 hours, because an admin session is a payment-approval
      session;
    * both have an absolute cap, so no session lives forever by being used.
    """

    #: Separate from SECURITY__SECRET_KEY so JWT signing can be rotated on its
    #: own. Falls back to the application secret when unset.
    jwt_secret_key: SecretStr | None = None
    jwt_issuer: str = "geekvpn"
    jwt_audience: str = "geekvpn-clients"

    access_token_ttl_minutes: int = 15

    user_refresh_ttl_days: int = 30
    user_absolute_ttl_days: int = 180

    admin_refresh_ttl_hours: int = 12
    admin_absolute_ttl_hours: int = 24

    #: Empty means "any IP". Set it and only these addresses may reach the
    #: admin login endpoint.
    admin_ip_allowlist: tuple[str, ...] = ()

    #: One-time bootstrap of the first super admin. Remove after first boot.
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    @field_validator("admin_ip_allowlist", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @property
    def access_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_ttl_minutes)

    @property
    def user_refresh_ttl(self) -> timedelta:
        return timedelta(days=self.user_refresh_ttl_days)

    @property
    def user_absolute_ttl(self) -> timedelta:
        return timedelta(days=self.user_absolute_ttl_days)

    @property
    def admin_refresh_ttl(self) -> timedelta:
        return timedelta(hours=self.admin_refresh_ttl_hours)

    @property
    def admin_absolute_ttl(self) -> timedelta:
        return timedelta(hours=self.admin_absolute_ttl_hours)


class Settings(BaseSettings):
    """Root settings object. Inject it; never read ``os.environ`` elsewhere."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @property
    def jwt_secret(self) -> str:
        secret = self.auth.jwt_secret_key or self.security.secret_key
        return secret.get_secret_value()

    @model_validator(mode="after")
    def _production_guardrails(self) -> Settings:
        """Fail fast at boot rather than leak an insecure default into production."""
        if not self.app.env.is_deployed:
            return self

        problems: list[str] = []
        if self.app.debug:
            problems.append("APP__DEBUG must be false outside local")
        if not self.logging.json:
            problems.append("LOGGING__JSON must be true outside local")
        if self.security.secret_key.get_secret_value().startswith(INSECURE_SECRET_PREFIX):
            problems.append("SECURITY__SECRET_KEY must be set")
        if len(self.jwt_secret) < 32:
            problems.append("The JWT signing secret must be at least 32 characters")
        if self.postgres.password.get_secret_value() in {"", "geekvpn", "postgres"}:
            problems.append("POSTGRES__PASSWORD must not be a default value")
        if not self.telegram.bot_token.get_secret_value():
            problems.append("TELEGRAM__BOT_TOKEN is required to verify Telegram logins")
        if not self.telegram.webhook_secret.get_secret_value():
            problems.append("TELEGRAM__WEBHOOK_SECRET is required")
        if self.auth.bootstrap_admin_password is not None:
            problems.append("AUTH__BOOTSTRAP_ADMIN_PASSWORD must be removed after the first boot")
        master_key = self.security.encryption_master_key.get_secret_value()
        if master_key.startswith(INSECURE_SECRET_PREFIX):
            problems.append("SECURITY__ENCRYPTION_MASTER_KEY must be set")
        if len(master_key) < 32:
            problems.append("SECURITY__ENCRYPTION_MASTER_KEY must be at least 32 characters")
        if master_key == self.security.secret_key.get_secret_value():
            # Not a style rule. Sharing one secret means the JWT key can never be
            # rotated without re-encrypting every stored card number, so the two
            # rotations become permanently coupled and neither ever happens.
            problems.append("SECURITY__ENCRYPTION_MASTER_KEY must differ from SECURITY__SECRET_KEY")
        if "*" in self.security.cors_origins:
            problems.append("SECURITY__CORS_ORIGINS must list exact origins, never '*'")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
