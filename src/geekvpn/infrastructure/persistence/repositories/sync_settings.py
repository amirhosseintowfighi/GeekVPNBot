"""Reading declared settings from the synchronous side.

`SettingsService` is async, and the payment scope's event handlers cannot
await it. This reads the same rows through the same `SettingDefinition`, so a
value is coerced and defaulted exactly as the async side would - one key, one
meaning, whichever scope asks.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from geekvpn.application.platform.settings_service import SettingDefinition
from geekvpn.domain.base.errors import ValidationError
from geekvpn.infrastructure.persistence.models.settings import SettingModel


class SyncSettings:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get[T: bool | int | float | str | list[Any] | dict[str, Any]](
        self, definition: SettingDefinition[T]
    ) -> T:
        row = self._session.get(SettingModel, definition.key)
        if row is None:
            return definition.default
        try:
            return definition.coerce(row.value)
        except ValidationError:
            return definition.default


__all__ = ["SyncSettings"]
