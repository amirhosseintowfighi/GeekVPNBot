"""Persistence ports.

The application depends on these `Protocol`s; `infrastructure.persistence`
implements them. Tests use in-memory fakes, which is why every identity use
case can be tested without Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.audit.entry import AuditEntry
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.session import RefreshToken, RevocationReason, Session
from geekvpn.domain.identity.user import User


@runtime_checkable
class UserRepository(Protocol):
    async def get(self, user_id: uuid.UUID) -> User | None: ...

    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...

    async def get_by_referral_code(self, code: str) -> User | None: ...

    async def add(self, user: User) -> None: ...

    async def update(self, user: User) -> None: ...


@runtime_checkable
class AdminRepository(Protocol):
    async def get(self, admin_id: uuid.UUID) -> Admin | None: ...

    async def get_by_username(self, username: str) -> Admin | None: ...

    async def get_by_telegram_id(self, telegram_id: int) -> Admin | None: ...

    async def add(self, admin: Admin) -> None: ...

    async def update(self, admin: Admin) -> None: ...

    async def list_all(self) -> Sequence[Admin]: ...

    async def count(self) -> int: ...


@runtime_checkable
class SessionRepository(Protocol):
    async def get(self, session_id: uuid.UUID) -> Session | None: ...

    async def add(self, session: Session) -> None: ...

    async def update(self, session: Session) -> None: ...

    async def list_active_for_subject(
        self, subject_id: uuid.UUID, *, subject_type: SubjectType, now: datetime
    ) -> Sequence[Session]: ...

    async def revoke_all_for_subject(
        self,
        subject_id: uuid.UUID,
        *,
        subject_type: SubjectType,
        reason: RevocationReason,
        now: datetime,
        except_session_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every live session for one subject.

        `subject_type` is part of the key, not decoration. Customers and admins
        live in different tables with independently generated UUIDs, so id
        alone is not a safe identifier for a destructive bulk operation.
        """
        ...

    # -- refresh token chain ----------------------------------------------

    async def add_refresh_token(self, token: RefreshToken) -> None: ...

    async def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    async def mark_refresh_token_used(
        self, token_id: uuid.UUID, *, replaced_by_id: uuid.UUID, now: datetime
    ) -> bool:
        """Atomically claim a refresh token.

        Returns True when this caller won the race, False when the token had
        already been spent. That boolean is the entire concurrency guarantee of
        refresh rotation, so an implementation MUST make the UPDATE conditional
        on the token still being unused.
        """
        ...

    async def revoke_refresh_tokens_for_session(
        self, session_id: uuid.UUID, *, now: datetime
    ) -> int: ...

    async def delete_expired(self, *, now: datetime) -> int: ...


@runtime_checkable
class AuditLogRepository(Protocol):
    async def add(self, entry: AuditEntry) -> None: ...

    async def search(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AuditEntry]: ...
