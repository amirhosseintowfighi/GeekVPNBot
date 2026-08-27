"""The customer aggregate.

Phase 2 scope: identity only. Wallet balance, subscriptions and orders belong
to other aggregates and are referenced by id, never embedded here - a user row
must never be a god object.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.identity.enums import AuthMethod, Language, UserStatus
from geekvpn.domain.identity.errors import AccountSuspendedError
from geekvpn.domain.identity.events import UserAuthenticated, UserRegistered, UserSuspended


class User(AggregateRoot[uuid.UUID]):
    """A Telegram customer.

    `telegram_id` is the natural key. It is a stable 64-bit integer that
    Telegram never reuses, so it is the only trustworthy identifier we have -
    usernames change, phone numbers change, display names change.
    """

    __slots__ = (
        "created_at",
        "first_name",
        "is_premium",
        "language",
        "last_name",
        "last_seen_at",
        "photo_url",
        "referral_code",
        "referred_by_code",
        "reseller_id",
        "status",
        "suspended_reason",
        "telegram_id",
        "username",
    )

    def __init__(
        self,
        entity_id: uuid.UUID,
        *,
        telegram_id: int,
        reseller_id: str | None = None,
        referral_code: str,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language: Language = Language.FA,
        status: UserStatus = UserStatus.ACTIVE,
        is_premium: bool = False,
        photo_url: str | None = None,
        referred_by_code: str | None = None,
        last_seen_at: datetime | None = None,
        suspended_reason: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(entity_id)
        self.telegram_id = telegram_id
        #: Which shop this person is a customer of. ``None`` is the
        #: platform's own bot. A Telegram account can be a customer of
        #: several shops, and each of those is a separate person here -
        #: separate wallet, separate subscriptions, separate tickets.
        self.reseller_id = reseller_id
        self.referral_code = referral_code
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.language = language
        self.status = status
        self.is_premium = is_premium
        self.photo_url = photo_url
        self.referred_by_code = referred_by_code
        self.last_seen_at = last_seen_at
        self.suspended_reason = suspended_reason
        self.created_at = created_at

    # -- factories ---------------------------------------------------------

    @classmethod
    def register(
        cls,
        *,
        user_id: uuid.UUID,
        telegram_id: int,
        referral_code: str,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language: Language = Language.FA,
        is_premium: bool = False,
        photo_url: str | None = None,
        referred_by_code: str | None = None,
        reseller_id: str | None = None,
        now: datetime | None = None,
    ) -> User:
        user = cls(
            user_id,
            telegram_id=telegram_id,
            reseller_id=reseller_id,
            referral_code=referral_code,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language=language,
            is_premium=is_premium,
            photo_url=photo_url,
            # A user cannot refer themselves, whatever the deep link says.
            referred_by_code=None if referred_by_code == referral_code else referred_by_code,
            last_seen_at=now,
            created_at=now,
        )
        user.record(
            UserRegistered(
                user_id=user_id,
                telegram_id=telegram_id,
                referral_code=referral_code,
                referred_by_code=user.referred_by_code,
            )
        )
        return user

    # -- behaviour ---------------------------------------------------------

    @property
    def display_name(self) -> str:
        parts = [part for part in (self.first_name, self.last_name) if part]
        if parts:
            return " ".join(parts)
        return f"@{self.username}" if self.username else f"user-{self.telegram_id}"

    def refresh_profile(
        self,
        *,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language: Language | None = None,
        is_premium: bool | None = None,
        photo_url: str | None = None,
    ) -> bool:
        """Sync the profile from the latest Telegram payload.

        Returns whether anything changed, so the caller can skip a pointless
        UPDATE on every single request - this runs on every authentication.
        """
        before = (
            self.username,
            self.first_name,
            self.last_name,
            self.language,
            self.is_premium,
            self.photo_url,
        )
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        if language is not None:
            self.language = language
        if is_premium is not None:
            self.is_premium = is_premium
        if photo_url is not None:
            self.photo_url = photo_url
        after = (
            self.username,
            self.first_name,
            self.last_name,
            self.language,
            self.is_premium,
            self.photo_url,
        )
        return before != after

    def ensure_can_authenticate(self) -> None:
        if not self.status.can_authenticate:
            raise AccountSuspendedError(reason=self.suspended_reason)

    def mark_authenticated(self, *, method: AuthMethod, now: datetime) -> None:
        self.ensure_can_authenticate()
        self.last_seen_at = now
        self.record(UserAuthenticated(user_id=self.id, method=method))

    def suspend(self, *, reason: str) -> None:
        self.status = UserStatus.SUSPENDED
        self.suspended_reason = reason
        self.record(UserSuspended(user_id=self.id, reason=reason))

    def reinstate(self) -> None:
        self.status = UserStatus.ACTIVE
        self.suspended_reason = None
