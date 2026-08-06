"""Admin repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import AdminStatus
from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.infrastructure.persistence.models.identity import AdminModel


class SqlAlchemyAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, admin_id: uuid.UUID) -> Admin | None:
        model = await self._session.get(AdminModel, admin_id)
        return _to_domain(model) if model else None

    async def get_by_username(self, username: str) -> Admin | None:
        stmt = select(AdminModel).where(AdminModel.username == username.lower())
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def get_by_telegram_id(self, telegram_id: int) -> Admin | None:
        stmt = select(AdminModel).where(AdminModel.telegram_id == telegram_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def add(self, admin: Admin) -> None:
        self._session.add(
            AdminModel(
                id=admin.id,
                username=admin.username,
                email=admin.email,
                password_hash=admin.password_hash,
                role=admin.role.value,
                status=admin.status.value,
                granted_permissions=_dump(admin.granted_permissions),
                denied_permissions=_dump(admin.denied_permissions),
                totp_secret=admin.totp_secret,
                is_totp_enabled=admin.is_totp_enabled,
                telegram_id=admin.telegram_id,
                failed_attempts=admin.failed_attempts,
                locked_until=admin.locked_until,
                last_login_at=admin.last_login_at,
                password_changed_at=admin.password_changed_at,
            )
        )
        await self._session.flush()

    async def update(self, admin: Admin) -> None:
        model = await self._session.get(AdminModel, admin.id)
        if model is None:  # pragma: no cover
            return
        model.username = admin.username
        model.email = admin.email
        model.password_hash = admin.password_hash
        model.role = admin.role.value
        model.status = admin.status.value
        model.granted_permissions = _dump(admin.granted_permissions)
        model.denied_permissions = _dump(admin.denied_permissions)
        model.totp_secret = admin.totp_secret
        model.is_totp_enabled = admin.is_totp_enabled
        model.telegram_id = admin.telegram_id
        model.failed_attempts = admin.failed_attempts
        model.locked_until = admin.locked_until
        model.last_login_at = admin.last_login_at
        model.password_changed_at = admin.password_changed_at
        await self._session.flush()

    async def count(self) -> int:
        stmt = select(func.count()).select_from(AdminModel)
        return int((await self._session.execute(stmt)).scalar_one())


def _dump(permissions: frozenset[Permission]) -> list[str]:
    return sorted(permission.value for permission in permissions)


def _load(values: list[str] | None) -> frozenset[Permission]:
    """Unknown permission strings are dropped, not fatal.

    A permission removed from the code must not make an admin unloadable.
    """
    if not values:
        return frozenset()
    known = {permission.value for permission in Permission}
    return frozenset(Permission(value) for value in values if value in known)


def _to_domain(model: AdminModel) -> Admin:
    return Admin(
        model.id,
        username=model.username,
        password_hash=model.password_hash,
        role=AdminRole(model.role),
        email=model.email,
        status=AdminStatus(model.status),
        granted_permissions=_load(model.granted_permissions),
        denied_permissions=_load(model.denied_permissions),
        totp_secret=model.totp_secret,
        is_totp_enabled=model.is_totp_enabled,
        telegram_id=model.telegram_id,
        failed_attempts=model.failed_attempts,
        locked_until=model.locked_until,
        last_login_at=model.last_login_at,
        password_changed_at=model.password_changed_at,
        created_at=model.created_at,
    )
