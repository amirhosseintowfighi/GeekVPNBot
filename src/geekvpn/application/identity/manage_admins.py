"""Administrator lifecycle.

Every mutation here is audited with a before/after diff, because "who gave
themselves that permission?" must always be answerable.
"""

from __future__ import annotations

import uuid

from geekvpn.application.identity.dto import AdminProfile
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.passwords import PasswordHasher
from geekvpn.application.ports.repositories import AdminRepository, SessionRepository
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import NotFoundError, ValidationError
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import AdminStatus, SubjectType
from geekvpn.domain.identity.errors import AdminAlreadyExistsError
from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.domain.identity.session import RevocationReason

MIN_PASSWORD_LENGTH = 12


class ManageAdmins:
    def __init__(
        self,
        *,
        admins: AdminRepository,
        sessions: SessionRepository,
        passwords: PasswordHasher,
        clock: Clock,
        audit: AuditRecorder,
    ) -> None:
        self._admins = admins
        self._sessions = sessions
        self._passwords = passwords
        self._clock = clock
        self._audit = audit

    async def create(
        self,
        *,
        username: str,
        password: str,
        role: AdminRole,
        email: str | None = None,
        telegram_id: int | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> AdminProfile:
        username = username.strip().lower()
        _validate_password(password)

        if await self._admins.get_by_username(username) is not None:
            raise AdminAlreadyExistsError(username=username)

        now = self._clock.now()
        admin = Admin(
            uuid.uuid4(),
            username=username,
            password_hash=self._passwords.hash(password),
            role=role,
            email=email,
            telegram_id=telegram_id,
            password_changed_at=now,
            created_at=now,
        )
        await self._admins.add(admin)
        await self._audit.record(
            AuditAction.ADMIN_CREATED,
            actor_type=SubjectType.ADMIN if actor_id else SubjectType.SYSTEM,
            actor_id=actor_id,
            target_type="admin",
            target_id=str(admin.id),
            username=username,
            role=role.value,
        )
        return _profile(admin)

    async def change_role(
        self, admin_id: uuid.UUID, *, role: AdminRole, actor_id: uuid.UUID
    ) -> AdminProfile:
        admin = await self._require(admin_id)
        previous = admin.role
        admin.role = role
        await self._admins.update(admin)
        await self._audit.record(
            AuditAction.ADMIN_ROLE_CHANGED,
            actor_type=SubjectType.ADMIN,
            actor_id=actor_id,
            target_type="admin",
            target_id=str(admin.id),
            previous_role=previous.value,
            new_role=role.value,
        )
        return _profile(admin)

    async def set_permission_overrides(
        self,
        admin_id: uuid.UUID,
        *,
        granted: frozenset[Permission],
        denied: frozenset[Permission],
        actor_id: uuid.UUID,
    ) -> AdminProfile:
        admin = await self._require(admin_id)
        before = sorted(permission.value for permission in admin.permissions)
        admin.granted_permissions = granted
        admin.denied_permissions = denied
        await self._admins.update(admin)
        await self._audit.record(
            AuditAction.ADMIN_PERMISSIONS_CHANGED,
            actor_type=SubjectType.ADMIN,
            actor_id=actor_id,
            target_type="admin",
            target_id=str(admin.id),
            before=before,
            after=sorted(permission.value for permission in admin.permissions),
        )
        return _profile(admin)

    async def change_password(
        self, admin_id: uuid.UUID, *, new_password: str, actor_id: uuid.UUID
    ) -> None:
        """Change a password and kill every existing session.

        A password change that leaves old sessions alive does not lock out an
        attacker who already has one.
        """
        _validate_password(new_password)
        admin = await self._require(admin_id)
        now = self._clock.now()
        admin.set_password_hash(self._passwords.hash(new_password), now=now)
        await self._admins.update(admin)
        revoked = await self._sessions.revoke_all_for_subject(
            admin_id,
            subject_type=SubjectType.ADMIN,
            reason=RevocationReason.PASSWORD_CHANGED,
            now=now,
        )
        await self._audit.record(
            AuditAction.ADMIN_PASSWORD_CHANGED,
            actor_type=SubjectType.ADMIN,
            actor_id=actor_id,
            target_type="admin",
            target_id=str(admin_id),
            revoked_sessions=revoked,
        )

    async def disable(self, admin_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        admin = await self._require(admin_id)
        now = self._clock.now()
        admin.status = AdminStatus.DISABLED
        await self._admins.update(admin)
        await self._sessions.revoke_all_for_subject(
            admin_id,
            subject_type=SubjectType.ADMIN,
            reason=RevocationReason.ADMIN_REVOKED,
            now=now,
        )
        await self._audit.record(
            AuditAction.ADMIN_DISABLED,
            actor_type=SubjectType.ADMIN,
            actor_id=actor_id,
            target_type="admin",
            target_id=str(admin_id),
        )

    async def _require(self, admin_id: uuid.UUID) -> Admin:
        admin = await self._admins.get(admin_id)
        if admin is None:
            raise NotFoundError("Administrator not found.", admin_id=str(admin_id))
        return admin


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            min_length=MIN_PASSWORD_LENGTH,
        )


def _profile(admin: Admin) -> AdminProfile:
    return AdminProfile(
        id=admin.id,
        username=admin.username,
        role=admin.role.value,
        permissions=tuple(sorted(p.value for p in admin.permissions)),
        is_totp_enabled=admin.is_totp_enabled,
        last_login_at=admin.last_login_at,
    )
