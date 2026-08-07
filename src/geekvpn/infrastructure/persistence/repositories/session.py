"""Session and refresh-token persistence.

The important method here is `mark_refresh_token_used`: it is a conditional
UPDATE, not a read-then-write. Two concurrent refresh calls with the same token
(a mobile client retry, or an attacker racing the victim) must produce exactly
one winner, and the loser must be told so it can burn the session.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.session import RefreshToken, RevocationReason, Session
from geekvpn.infrastructure.persistence.models.identity import (
    RefreshTokenModel,
    SessionModel,
)


class SqlAlchemySessionRepository:
    """Implements `SessionRepository` over PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # -- sessions ----------------------------------------------------------

    async def get(self, session_id: uuid.UUID) -> Session | None:
        row = await self._db.get(SessionModel, session_id)
        return row.to_domain() if row is not None else None

    async def add(self, session: Session) -> None:
        self._db.add(SessionModel.from_domain(session))
        await self._db.flush()

    async def update(self, session: Session) -> None:
        row = await self._db.get(SessionModel, session.id)
        if row is None:
            self._db.add(SessionModel.from_domain(session))
        else:
            row.apply(session)
        await self._db.flush()

    async def list_active_for_subject(
        self, subject_id: uuid.UUID, *, subject_type: SubjectType, now: datetime
    ) -> Sequence[Session]:
        stmt = (
            select(SessionModel)
            .where(
                SessionModel.subject_id == subject_id,
                SessionModel.subject_type == subject_type.value,
                SessionModel.revoked_at.is_(None),
                SessionModel.absolute_expires_at > now,
            )
            .order_by(SessionModel.last_used_at.desc())
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        return [row.to_domain() for row in rows]

    async def revoke_all_for_subject(
        self,
        subject_id: uuid.UUID,
        *,
        subject_type: SubjectType,
        reason: RevocationReason,
        now: datetime,
        except_session_id: uuid.UUID | None = None,
    ) -> int:
        conditions = [
            SessionModel.subject_id == subject_id,
            SessionModel.subject_type == subject_type.value,
            SessionModel.revoked_at.is_(None),
        ]
        if except_session_id is not None:
            conditions.append(SessionModel.id != except_session_id)

        session_ids = (
            (await self._db.execute(select(SessionModel.id).where(*conditions))).scalars().all()
        )
        if not session_ids:
            return 0

        await self._db.execute(
            update(SessionModel)
            .where(SessionModel.id.in_(session_ids))
            .values(revoked_at=now, revocation_reason=reason.value)
        )
        await self._db.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.session_id.in_(session_ids),
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self._db.flush()
        return len(session_ids)

    # -- refresh tokens ----------------------------------------------------

    async def add_refresh_token(self, token: RefreshToken) -> None:
        self._db.add(RefreshTokenModel.from_domain(token))
        await self._db.flush()

    async def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        row = (await self._db.execute(stmt)).scalar_one_or_none()
        return row.to_domain() if row is not None else None

    async def mark_refresh_token_used(
        self, token_id: uuid.UUID, *, replaced_by_id: uuid.UUID, now: datetime
    ) -> bool:
        """Claim the token. True means this caller won the race.

        `used_at IS NULL` in the WHERE clause is the whole guarantee: under READ
        COMMITTED the second transaction blocks on the row lock, then
        re-evaluates the predicate and matches zero rows.
        """
        # An UPDATE/DELETE yields a CursorResult, which is what carries
        # rowcount; the declared Result type does not.
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                update(RefreshTokenModel)
                .where(
                    RefreshTokenModel.id == token_id,
                    RefreshTokenModel.used_at.is_(None),
                    RefreshTokenModel.revoked_at.is_(None),
                )
                .values(used_at=now, replaced_by_id=replaced_by_id)
            ),
        )
        await self._db.flush()
        return bool(result.rowcount == 1)

    async def revoke_refresh_tokens_for_session(
        self, session_id: uuid.UUID, *, now: datetime
    ) -> int:
        # An UPDATE/DELETE yields a CursorResult, which is what carries
        # rowcount; the declared Result type does not.
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                update(RefreshTokenModel)
                .where(
                    RefreshTokenModel.session_id == session_id,
                    RefreshTokenModel.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            ),
        )
        await self._db.flush()
        return int(result.rowcount or 0)

    async def delete_expired(self, *, now: datetime) -> int:
        """Housekeeping for the scheduler; expired rows carry no security value."""
        # An UPDATE/DELETE yields a CursorResult, which is what carries
        # rowcount; the declared Result type does not.
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                delete(RefreshTokenModel).where(RefreshTokenModel.expires_at < now)
            ),
        )
        await self._db.flush()
        return int(result.rowcount or 0)
