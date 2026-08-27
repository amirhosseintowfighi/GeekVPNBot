"""Telegram authentication port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from geekvpn.domain.identity.enums import AuthMethod


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    """A Telegram profile whose authenticity has been cryptographically proven."""

    telegram_id: int
    method: AuthMethod
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    photo_url: str | None = None
    is_premium: bool = False
    start_param: str | None = None
    #: Which shop's bot this update arrived at. ``None`` is the
    #: platform's own. A Telegram account is a separate customer in
    #: each shop - separate wallet, separate subscriptions - so this
    #: decides *which* person is being authenticated, not merely where
    #: they came from.
    reseller_id: str | None = None


@runtime_checkable
class TelegramAuthVerifier(Protocol):
    def verify_mini_app(
        self, init_data: str, *, max_age_seconds: int | None = None
    ) -> TelegramIdentity:
        """Verify a Mini App `initData` string.

        `max_age_seconds` overrides the configured freshness window for this
        one call. A login may accept day-old initData; a per-request credential
        replayed on every call must not.
        """
        ...

    def verify_login_widget(self, payload: dict[str, str]) -> TelegramIdentity:
        """Verify a Telegram Login Widget callback payload."""
        ...
