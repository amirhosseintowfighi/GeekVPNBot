"""Runtime settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.api.schemas_auth import SettingResponse, SettingUpdateRequest
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep, requires

router = APIRouter(prefix="/admin/settings", tags=["settings"])


@router.get(
    "",
    response_model=list[SettingResponse],
    summary="Every declared runtime setting with its effective value",
    dependencies=[Depends(requires(Permission.SETTINGS_READ))],
)
async def list_settings(scope: ScopeDep) -> list[SettingResponse]:
    records = await scope.settings_service.list_all()
    return [
        SettingResponse(
            key=record.key,
            value=record.display_value,
            description=record.description,
            is_secret=record.is_secret,
            updated_at=record.updated_at,
        )
        for record in records
    ]


@router.put(
    "/{key}",
    response_model=SettingResponse,
    summary="Update a runtime setting",
    dependencies=[Depends(requires(Permission.SETTINGS_WRITE))],
)
async def update_setting(
    key: str, payload: SettingUpdateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> SettingResponse:
    record = await scope.settings_service.set(
        key, payload.value, actor_id=actor.subject_id, actor_label=actor.role
    )
    return SettingResponse(
        key=record.key,
        value=record.display_value,
        description=record.description,
        is_secret=record.is_secret,
        updated_at=record.updated_at,
    )
