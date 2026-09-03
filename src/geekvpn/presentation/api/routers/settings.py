"""Runtime settings endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from geekvpn.application.platform.settings_service import (
    SETTING_REGISTRY,
    SettingDefinition,
)
from geekvpn.application.ports.settings_store import SettingRecord
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
    return [_view(record) for record in records]


def _view(record: SettingRecord) -> SettingResponse:
    declared = _definition(record.key)
    # Label and kind come from the registry, which is where the declaration
    # lives. A record carries what is *stored*; how to show it belongs to the
    # declaration, and the panel must not have to infer either.
    return SettingResponse(
        key=record.key,
        value=record.display_value,
        description=record.description,
        label_fa=declared.label_fa if declared else record.key,
        kind=declared.kind if declared else "text",
        is_secret=record.is_secret,
        updated_at=record.updated_at,
    )


def _definition(key: str) -> SettingDefinition[Any] | None:
    """The declaration behind a stored row, if we still declare it.

    `None` for a key that was removed from the registry but is still in
    the table. Showing it as plain text is better than hiding a value
    that is, as far as the database is concerned, still set.
    """
    return SETTING_REGISTRY.get(key)


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
