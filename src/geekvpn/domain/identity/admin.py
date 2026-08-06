"""The administrator aggregate.

An admin is not a user with a flag. Different credentials, different session
lifetime, different table, different audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.identity.enums import AdminStatus
from geekvpn.domain.identity.errors import (
    AccountLockedError,
    AccountSuspendedError,
    MissingPermissionError,
)
from geekvpn.domain.identity.permissions import AdminRole, Permission, resolve_permissions

#: After this many consecutive failures the account locks. Chosen to stop
#: credential stuffing while staying above the number of typos a tired human
#: makes in a row.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class Admin(AggregateRoot[uuid.UUID]):
    """A staff account with a role and optional per-permission overrides."""

    __slots__ = (
        "created_at",
        "denied_permissions",
        "email",
        "failed_attempts",
        "granted_permissions",
        "is_totp_enabled",
        "last_login_at",
        "locked_until",
        "password_changed_at",
        "password_hash",
        "role",
        "status",
        "telegram_id",
        "totp_secret",
        "username",
    )

    def __init__(
        self,
        entity_id: uuid.UUID,
        *,
        username: str,
        password_hash: str,
        role: AdminRole,
        email: str | None = None,
        status: AdminStatus = AdminStatus.ACTIVE,
        granted_permissions: frozenset[Permission] = frozenset(),
        denied_permissions: frozenset[Permission] = frozenset(),
        totp_secret: str | None = None,
        is_totp_enabled: bool = False,
        telegram_id: int | None = None,
        failed_attempts: int = 0,
        locked_until: datetime | None = None,
        last_login_at: datetime | None = None,
        password_changed_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(entity_id)
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.email = email
        self.status = status
        self.granted_permissions = granted_permissions
        self.denied_permissions = denied_permissions
        self.totp_secret = totp_secret
        self.is_totp_enabled = is_totp_enabled
        self.telegram_id = telegram_id
        self.failed_attempts = failed_attempts
        self.locked_until = locked_until
        self.last_login_at = last_login_at
        self.password_changed_at = password_changed_at
        self.created_at = created_at

    # -- authorisation -----------------------------------------------------

    @property
    def permissions(self) -> frozenset[Permission]:
        """Effective permissions. Denials override everything, including role."""
        return resolve_permissions(
            self.role,
            granted=self.granted_permissions,
            denied=self.denied_permissions,
        )

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require_permission(self, permission: Permission) -> None:
        if not self.has_permission(permission):
            raise MissingPermissionError(required=permission.value)

    # -- authentication state machine --------------------------------------

    def is_locked(self, *, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > now

    def ensure_can_authenticate(self, *, now: datetime) -> None:
        if not self.status.can_authenticate:
            raise AccountSuspendedError()
        if self.is_locked(now=now):
            raise AccountLockedError(locked_until=self.locked_until.isoformat())

    def register_failed_attempt(self, *, now: datetime) -> None:
        """Count a failure and lock the account once the threshold is crossed."""
        self.failed_attempts += 1
        if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
            self.locked_until = now + LOCKOUT_DURATION
            self.failed_attempts = 0

    def register_successful_login(self, *, now: datetime) -> None:
        self.failed_attempts = 0
        self.locked_until = None
        self.last_login_at = now

    def set_password_hash(self, password_hash: str, *, now: datetime) -> None:
        self.password_hash = password_hash
        self.password_changed_at = now

    def enable_totp(self, secret: str) -> None:
        self.totp_secret = secret
        self.is_totp_enabled = True

    def disable_totp(self) -> None:
        self.totp_secret = None
        self.is_totp_enabled = False

    @property
    def requires_totp(self) -> bool:
        """Super admins must use 2FA; for everyone else it is opt-in.

        The account that can create other admins is the one worth stealing.
        """
        return self.is_totp_enabled or self.role is AdminRole.SUPER_ADMIN
