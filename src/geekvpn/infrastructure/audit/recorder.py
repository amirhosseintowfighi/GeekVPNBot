"""The audit recorder.

Two behaviours worth knowing:

1. It pulls the **correlation id** out of the logging context automatically, so
   every audit row links back to the exact request that produced it and no
   caller has to remember to pass it.
2. It writes to Postgres **and** emits a structured log line. The database row
   is the legal record; the log line is what a Grafana alert watches. Losing
   one does not lose the other.

It does not swallow database errors. An audit write that silently fails is
worse than no audit log, because it produces false confidence.
"""

from __future__ import annotations

import uuid
from typing import Any

from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.repositories import AuditLogRepository
from geekvpn.domain.audit.entry import AuditAction, AuditEntry, AuditOutcome
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.infrastructure.logging.context import get_correlation_id
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger("geekvpn.audit")

#: Metadata keys are values, not secrets, but a caller can still make a
#: mistake. These never reach the database.
_FORBIDDEN_METADATA_KEYS = frozenset(
    {"password", "token", "secret", "init_data", "authorization", "totp_code"}
)


class AuditLogRecorder:
    def __init__(self, *, repository: AuditLogRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

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
    ) -> None:
        entry = AuditEntry(
            id=uuid.uuid4(),
            action=action,
            outcome=outcome,
            occurred_at=self._clock.now(),
            actor_type=actor_type,
            actor_id=actor_id,
            actor_label=actor_label,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            user_agent=user_agent,
            correlation_id=get_correlation_id(),
            metadata=_clean(metadata),
        )
        await self._repository.add(entry)

        logger.info(
            "audit",
            action=action.value,
            outcome=outcome.value,
            actor_type=actor_type.value,
            actor_id=str(actor_id) if actor_id else None,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
        )


def _clean(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop forbidden keys and anything that will not survive JSON encoding."""
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if key.lower() in _FORBIDDEN_METADATA_KEYS:
            continue
        if isinstance(value, uuid.UUID):
            cleaned[key] = str(value)
        elif isinstance(value, (str, int, float, bool, type(None), list, dict)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned
