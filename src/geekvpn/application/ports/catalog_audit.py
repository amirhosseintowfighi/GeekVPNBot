"""The slice of the Phase 2 audit recorder that the catalog context uses.

A structural Protocol rather than an import of the concrete recorder, so the
admin services can be unit-tested against a list-backed fake and the catalog
never depends on the identity module.

Only the arguments the catalog actually passes are declared. The concrete
Phase 2 recorder accepts a wider signature (outcome, actor_type, ip, user
agent) and satisfies this Protocol structurally because those extras all have
defaults.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CatalogAuditRecorder(Protocol):
    """Records one auditable catalog operation."""

    async def record(
        self,
        action: Any,
        *,
        actor_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        **metadata: Any,
    ) -> None: ...
