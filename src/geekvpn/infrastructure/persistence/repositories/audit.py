"""Audit repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.audit.entry import AuditAction, AuditEntry, AuditOutcome
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.infrastructure.persistence.models.audit import AuditLogModel


class SqlAlchemyAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditLogModel(
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
                user_agent=entry.user_agent[:512] if entry.user_agent else None,
                correlation_id=entry.correlation_id,
                audit_metadata=entry.metadata,
            )
        )
        await self._session.flush()

    async def search(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AuditEntry]:
        stmt = select(AuditLogModel).order_by(AuditLogModel.occurred_at.desc())
        if actor_id is not None:
            stmt = stmt.where(AuditLogModel.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditLogModel.action == action)
        if since is not None:
            stmt = stmt.where(AuditLogModel.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(AuditLogModel.occurred_at <= until)
        # Hard cap: an unbounded audit query is a memory incident.
        stmt = stmt.limit(min(limit, 200)).offset(offset)

        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(model) for model in models]


def _to_domain(model: AuditLogModel) -> AuditEntry:
    return AuditEntry(
        id=model.id,
        action=AuditAction(model.action),
        outcome=AuditOutcome(model.outcome),
        occurred_at=model.occurred_at,
        actor_type=SubjectType(model.actor_type),
        actor_id=model.actor_id,
        actor_label=model.actor_label,
        target_type=model.target_type,
        target_id=model.target_id,
        ip=model.ip,
        user_agent=model.user_agent,
        correlation_id=model.correlation_id,
        metadata=dict(model.audit_metadata or {}),
    )
