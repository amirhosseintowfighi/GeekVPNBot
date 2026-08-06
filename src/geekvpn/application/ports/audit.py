"""Audit recording port.

A separate port from the repository because most callers only ever want to say
"this happened" and should not have to build an `AuditEntry` by hand, generate
a uuid, or find the correlation id.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.enums import SubjectType


@runtime_checkable
class AuditRecorder(Protocol):
    async def record(
        self,
        action: AuditAction,
        *,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        actor_type: SubjectType = SubjectType.SYSTEM,
        actor_id: uuid.UUID | None = None,
        actor_label: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        **metadata: Any,
    ) -> None: ...
