"""Runtime settings port.

Two different things are called "settings" and conflating them is a mistake:

* **Boot configuration** (`infrastructure.config.Settings`) - secrets, DSNs,
  ports. Immutable, from the environment, requires a restart.
* **Runtime settings** (this port) - values an admin changes from the panel
  without a deploy: maintenance mode, trial size, support hours, feature
  flags.

Runtime settings are stored in Postgres, cached in Redis, typed on read, and
audited on write.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SettingRecord:
    key: str
    value: Any
    description: str | None = None
    is_secret: bool = False
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None

    @property
    def display_value(self) -> Any:
        """Never show a secret in a list response."""
        return "***" if self.is_secret else self.value


@runtime_checkable
class SettingsStore(Protocol):
    async def get(self, key: str) -> SettingRecord | None: ...

    async def all(self) -> Sequence[SettingRecord]: ...

    async def set(
        self,
        key: str,
        value: Any,
        *,
        updated_by: uuid.UUID | None = None,
        description: str | None = None,
        is_secret: bool = False,
    ) -> SettingRecord: ...

    async def delete(self, key: str) -> bool: ...
