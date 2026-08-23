"""Data transfer objects crossing the application boundary.

These are not pydantic models: the application layer must not depend on a
web framework's serialisation library. The presentation layer maps them onto
its own response schemas.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from geekvpn.domain.identity.enums import AuthMethod, Language, SubjectType


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Where a command came from. Threaded into sessions and audit rows."""

    ip: str | None = None
    user_agent: str | None = None
    device_label: str | None = None


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID
    token_type: str = "Bearer"  # noqa: S105 - a scheme name, not a credential


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: uuid.UUID
    telegram_id: int
    display_name: str
    username: str | None
    language: Language
    status: str
    referral_code: str
    is_premium: bool
    photo_url: str | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminProfile:
    id: uuid.UUID
    username: str
    role: str
    permissions: tuple[str, ...]
    is_totp_enabled: bool
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    tokens: TokenPair
    subject_type: SubjectType
    method: AuthMethod
    user: UserProfile | None = None
    admin: AdminProfile | None = None
    is_new_user: bool = False


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    ip: str | None
    user_agent: str | None
    device_label: str | None
    is_current: bool


@dataclass(frozen=True, slots=True)
class TotpEnrolment:
    """A freshly issued second factor, returned exactly once.

    The secret is never readable again: it is stored encrypted and every later
    read is a verification, not a disclosure. Whoever runs the enrolment has
    this one chance to scan it into an authenticator.
    """

    username: str
    secret: str
    provisioning_uri: str
