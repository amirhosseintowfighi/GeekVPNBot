"""Identity domain events.

These are the contract other contexts subscribe to. `auth.token_reuse_detected`
in particular is what a future alerting rule will page on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from geekvpn.domain.base.events import DomainEvent
from geekvpn.domain.identity.enums import AuthMethod


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRegistered(DomainEvent):
    name: ClassVar[str] = "identity.user.registered.v1"

    user_id: uuid.UUID
    telegram_id: int
    referral_code: str
    referred_by_code: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "telegram_id": self.telegram_id,
            "referral_code": self.referral_code,
            "referred_by_code": self.referred_by_code,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class UserAuthenticated(DomainEvent):
    name: ClassVar[str] = "identity.user.authenticated.v1"

    user_id: uuid.UUID
    method: AuthMethod

    def payload(self) -> dict[str, Any]:
        return {"user_id": str(self.user_id), "method": self.method.value}


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSuspended(DomainEvent):
    name: ClassVar[str] = "identity.user.suspended.v1"

    user_id: uuid.UUID
    reason: str

    def payload(self) -> dict[str, Any]:
        return {"user_id": str(self.user_id), "reason": self.reason}


@dataclass(frozen=True, slots=True, kw_only=True)
class AdminAuthenticated(DomainEvent):
    name: ClassVar[str] = "identity.admin.authenticated.v1"

    admin_id: uuid.UUID
    role: str

    def payload(self) -> dict[str, Any]:
        return {"admin_id": str(self.admin_id), "role": self.role}


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenReuseDetected(DomainEvent):
    """Emitted when a rotated refresh token is presented again."""

    name: ClassVar[str] = "identity.auth.token_reuse_detected.v1"

    session_id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    ip: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "subject_type": self.subject_type,
            "subject_id": str(self.subject_id),
            "ip": self.ip,
        }
