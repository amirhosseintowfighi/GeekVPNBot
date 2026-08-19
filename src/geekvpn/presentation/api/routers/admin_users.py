"""Administrator management and the audit log reader.

Every route here is permission-guarded, and the guard is declarative. There is
no `if subject.role == "super_admin"` anywhere in this file - that is the whole
point of the permission system.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import ConfigDict, Field

from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.schemas_auth import (
    AdminResponse,
    AuditEntryResponse,
    MessageResponse,
)
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep, requires

router = APIRouter(prefix="/admin", tags=["administration"])


class CreateAdminRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: AdminRole
    email: str | None = Field(default=None, max_length=256)
    telegram_id: int | None = None


class ChangeRoleRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    role: AdminRole


class PermissionOverridesRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    granted: list[Permission] = Field(default_factory=list)
    denied: list[Permission] = Field(default_factory=list)


@router.get(
    "/admins",
    response_model=list[AdminResponse],
    summary="Every administrator",
    dependencies=[Depends(requires(Permission.ADMINS_READ))],
)
async def list_admins(scope: ScopeDep, actor: CurrentAdmin) -> list[AdminResponse]:
    """The permissions screen needs to show who has what.

    There was no way to read this: an operator could be created, given a role
    and deleted, but never listed, so the panel's permissions page had nothing
    to render and asked for a route that did not exist.
    """
    admins = await scope.admins.list_all()
    return [
        AdminResponse(
            id=admin.id,
            username=admin.username,
            role=admin.role,
            permissions=sorted(str(permission) for permission in admin.permissions),
            is_totp_enabled=admin.is_totp_enabled,
            last_login_at=admin.last_login_at,
        )
        for admin in admins
    ]


@router.post(
    "/admins",
    response_model=AdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an administrator",
    dependencies=[Depends(requires(Permission.ADMINS_WRITE))],
)
async def create_admin(
    payload: CreateAdminRequest, actor: CurrentAdmin, scope: ScopeDep
) -> AdminResponse:
    profile = await scope.manage_admins.create(
        username=payload.username,
        password=payload.password,
        role=payload.role,
        email=payload.email,
        telegram_id=payload.telegram_id,
        actor_id=actor.subject_id,
    )
    return AdminResponse(
        id=profile.id,
        username=profile.username,
        role=profile.role,
        permissions=list(profile.permissions),
        is_totp_enabled=profile.is_totp_enabled,
        last_login_at=profile.last_login_at,
    )


@router.put(
    "/admins/{admin_id}/role",
    response_model=AdminResponse,
    summary="Change an administrator's role",
    dependencies=[Depends(requires(Permission.ADMINS_WRITE))],
)
async def change_role(
    admin_id: uuid.UUID,
    payload: ChangeRoleRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> AdminResponse:
    profile = await scope.manage_admins.change_role(
        admin_id, role=payload.role, actor_id=actor.subject_id
    )
    return AdminResponse(
        id=profile.id,
        username=profile.username,
        role=profile.role,
        permissions=list(profile.permissions),
        is_totp_enabled=profile.is_totp_enabled,
        last_login_at=profile.last_login_at,
    )


@router.put(
    "/admins/{admin_id}/permissions",
    response_model=AdminResponse,
    summary="Set per-administrator permission overrides",
    dependencies=[Depends(requires(Permission.ADMINS_WRITE))],
)
async def set_permissions(
    admin_id: uuid.UUID,
    payload: PermissionOverridesRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> AdminResponse:
    profile = await scope.manage_admins.set_permission_overrides(
        admin_id,
        granted=frozenset(payload.granted),
        denied=frozenset(payload.denied),
        actor_id=actor.subject_id,
    )
    return AdminResponse(
        id=profile.id,
        username=profile.username,
        role=profile.role,
        permissions=list(profile.permissions),
        is_totp_enabled=profile.is_totp_enabled,
        last_login_at=profile.last_login_at,
    )


@router.delete(
    "/admins/{admin_id}",
    response_model=MessageResponse,
    summary="Disable an administrator and end all of their sessions",
    dependencies=[Depends(requires(Permission.ADMINS_WRITE))],
)
async def disable_admin(
    admin_id: uuid.UUID, actor: CurrentAdmin, scope: ScopeDep
) -> MessageResponse:
    await scope.manage_admins.disable(admin_id, actor_id=actor.subject_id)
    return MessageResponse(message="Administrator disabled.")


@router.get(
    "/audit-logs",
    response_model=list[AuditEntryResponse],
    summary="Search the audit trail",
    dependencies=[Depends(requires(Permission.AUDIT_READ))],
)
async def search_audit_logs(
    scope: ScopeDep,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEntryResponse]:
    entries = await scope.audit_repository.search(
        actor_id=actor_id,
        action=action,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return [
        AuditEntryResponse(
            id=entry.id,
            action=entry.action.value,
            outcome=entry.outcome.value,
            occurred_at=entry.occurred_at,
            actor_type=entry.actor_type.value,
            actor_id=entry.actor_id,
            actor_label=entry.actor_label,
            target_type=entry.target_type,
            target_id=entry.target_id,
            ip=entry.ip,
            correlation_id=entry.correlation_id,
            metadata=entry.metadata,
        )
        for entry in entries
    ]
