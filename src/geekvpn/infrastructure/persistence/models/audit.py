"""The audit table.

Append-only is enforced by a database rule in the migration, not by hoping
application code behaves. If an attacker reaches the API, the audit trail of
what they did must survive them.

Retention: rows are never deleted by the application. Phase 5 partitions this
table by month and archives cold partitions to object storage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.domain.audit.entry import AuditOutcome
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.infrastructure.persistence.base import Base


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor_label: Mapped[str | None] = mapped_column(String(128))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN (" + ", ".join(f"'{m.value}'" for m in AuditOutcome) + ")",
            name="audit_logs_outcome",
        ),
        CheckConstraint(
            "actor_type IN (" + ", ".join(f"'{m.value}'" for m in SubjectType) + ")",
            name="audit_logs_actor_type",
        ),
        # "Everything this actor did, newest first" - the query support runs.
        Index("ix_audit_logs_actor_id_occurred_at", "actor_id", "occurred_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )
