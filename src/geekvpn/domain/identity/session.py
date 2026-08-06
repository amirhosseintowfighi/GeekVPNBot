"""Sessions and refresh tokens.

The model that matters
----------------------
A **session** is one device / one login. It owns a chain of **refresh tokens**;
every refresh rotates the current token and issues the next one. This is what
makes theft detectable:

    issue T1 -> refresh(T1) -> T1 used, issue T2 -> refresh(T2) -> ...

If T1 is ever presented again, two parties hold it. We cannot tell which one is
the attacker, so we destroy the whole session and force a fresh login. That is
the standard rotation-with-reuse-detection scheme (OAuth 2.1 BCP), and it is
the single most valuable thing in this module.

Refresh tokens are stored as a SHA-256 hash. A database leak must not hand the
attacker working credentials. They are high-entropy random strings, so a fast
hash is correct here - key stretching protects low-entropy secrets, and slowing
down a lookup on every refresh buys nothing.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from geekvpn.domain.base.entity import Entity
from geekvpn.domain.identity.enums import AuthMethod, SubjectType


class RevocationReason(enum.StrEnum):
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    TOKEN_REUSE = "token_reuse"  # noqa: S105 - a constant name, not a credential
    ADMIN_REVOKED = "admin_revoked"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - a constant name, not a credential
    ACCOUNT_SUSPENDED = "account_suspended"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Everything we know about where a session came from.

    Used for the "active devices" screen and for spotting a session that
    suddenly jumps country.
    """

    ip: str | None = None
    user_agent: str | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshToken:
    """One link in a session's rotation chain."""

    id: uuid.UUID
    session_id: uuid.UUID
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_id: uuid.UUID | None = None

    def is_expired(self, *, now: datetime) -> bool:
        return self.expires_at <= now

    @property
    def is_spent(self) -> bool:
        """Already rotated or explicitly revoked - presenting it again is reuse."""
        return self.used_at is not None or self.revoked_at is not None

    def is_usable(self, *, now: datetime) -> bool:
        return not self.is_spent and not self.is_expired(now=now)


class Session(Entity[uuid.UUID]):
    """One authenticated device."""

    __slots__ = (
        "absolute_expires_at",
        "auth_method",
        "created_at",
        "device",
        "last_used_at",
        "revocation_reason",
        "revoked_at",
        "subject_id",
        "subject_type",
    )

    def __init__(
        self,
        entity_id: uuid.UUID,
        *,
        subject_type: SubjectType,
        subject_id: uuid.UUID,
        auth_method: AuthMethod,
        created_at: datetime,
        absolute_expires_at: datetime,
        device: DeviceInfo = DeviceInfo(),
        last_used_at: datetime | None = None,
        revoked_at: datetime | None = None,
        revocation_reason: RevocationReason | None = None,
    ) -> None:
        super().__init__(entity_id)
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.auth_method = auth_method
        self.device = device
        self.created_at = created_at
        self.absolute_expires_at = absolute_expires_at
        self.last_used_at = last_used_at or created_at
        self.revoked_at = revoked_at
        self.revocation_reason = revocation_reason

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, *, now: datetime) -> bool:
        """Absolute lifetime cap.

        Sliding expiry alone means a stolen refresh token lives forever as long
        as it is used. The absolute cap guarantees every session eventually
        dies and the user re-authenticates.
        """
        return self.absolute_expires_at <= now

    def is_active(self, *, now: datetime) -> bool:
        return not self.is_revoked and not self.is_expired(now=now)

    def touch(self, *, now: datetime, device: DeviceInfo | None = None) -> None:
        self.last_used_at = now
        if device is not None:
            self.device = device

    def revoke(self, *, reason: RevocationReason, now: datetime) -> None:
        if self.is_revoked:
            return
        self.revoked_at = now
        self.revocation_reason = reason


@dataclass(frozen=True, slots=True)
class AuthenticatedSubject:
    """The decoded identity behind a request.

    Built from the access token alone, so authorising a request costs zero
    database queries. The trade-off - a permission change is not visible until
    the access token expires - is bounded by the short access-token TTL, and
    can be forced immediately by revoking the session.
    """

    subject_type: SubjectType
    subject_id: uuid.UUID
    session_id: uuid.UUID
    role: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.subject_type is SubjectType.ADMIN
