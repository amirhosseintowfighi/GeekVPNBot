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
from geekvpn.domain.identity.app_login import AppLoginRequest, AppLoginStatus
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.session import RefreshToken, RevocationReason, Session
from geekvpn.domain.identity.user import User


@runtime_checkable
class UserRepository(Protocol):
    async def get(self, user_id: uuid.UUID) -> User | None: ...

    async def get_by_telegram_id(
        self, telegram_id: int, *, reseller_id: uuid.UUID | None = None
    ) -> User | None:
        """One person, in one shop.

        `None` is the platform's own bot - a real answer, not "any shop". The
        same Telegram account is a different customer in each reseller's bot,
        with their own wallet and their own subscriptions.
        """
        ...

    async def get_by_referral_code(self, code: str) -> User | None: ...

    async def add(self, user: User) -> None: ...

    async def update(self, user: User) -> None: ...


@runtime_checkable
class ReferralRepository(Protocol):
    """The edge from a referrer to somebody who arrived on their link.

    An edge per invitee, written once at registration. Five different screens
    read this table - the customer's own referral page, the operator's
    programme report, three analytics queries - and until now nothing wrote to
    it, so every one of them answered "nobody has ever used your link".
    """

    async def record_signup(
        self,
        *,
        referral_id: str,
        referrer_telegram_id: int,
        invitee_telegram_id: int,
        code: str,
        joined_at: datetime,
    ) -> bool:
        """Record the edge. `False` if this invitee already had one.

        Idempotent because `/start ref_X` is a link people tap twice, and
        because the invitee column is unique - a second insert would abort the
        whole registration transaction over a duplicate tap.
        """
        ...


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


@runtime_checkable
class AppLoginRepository(Protocol):
    """App sign-in requests.

    Every state change is a conditional write that reports whether it won,
    never a read followed by a write: two taps on "approve", or two polls
    racing for the same tokens, must produce exactly one winner. The same
    pattern the refresh-token claim uses.
    """

    async def add(self, request: AppLoginRequest) -> None: ...

    async def get(self, request_id: uuid.UUID) -> AppLoginRequest | None: ...

    async def get_by_code_hash(self, code_hash: str) -> AppLoginRequest | None: ...

    async def get_by_poll_token_hash(self, poll_token_hash: str) -> AppLoginRequest | None: ...

    async def claim(self, request_id: uuid.UUID, *, telegram_user_id: int, now: datetime) -> bool:
        """Bind a pending, unexpired, unclaimed request to the account that opened its link."""
        ...

    async def decide(
        self,
        request_id: uuid.UUID,
        *,
        telegram_user_id: int,
        status: AppLoginStatus,
        now: datetime,
    ) -> bool:
        """Move a pending, unexpired request claimed by this account to `status`."""
        ...

    async def consume(self, request_id: uuid.UUID, *, now: datetime) -> bool:
        """Move an approved, unexpired request to consumed. At most one caller wins."""
        ...
