"""In-memory doubles.

Every identity use case is testable without Postgres or Redis because the
application depends on ports. These fakes are the payoff for that discipline -
if one of them is hard to write, the port is wrong.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from geekvpn.application.ports.rate_limiter import RateLimitVerdict
from geekvpn.application.ports.settings_store import SettingRecord
from geekvpn.domain.audit.entry import AuditAction, AuditEntry, AuditOutcome
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.session import RefreshToken, RevocationReason, Session
from geekvpn.domain.identity.user import User


class FrozenClock:
    def __init__(self, moment: datetime | None = None) -> None:
        self.moment = moment or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.moment

    def advance(self, delta: timedelta) -> None:
        self.moment += delta


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, User] = {}

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self.items.get(user_id)

    async def get_by_telegram_id(
        self, telegram_id: int, *, reseller_id: uuid.UUID | None = None
    ) -> User | None:
        """Scoped by shop, like the real one.

        A fake that ignored `reseller_id` would pass every test while the
        thing it stands in for hands a reseller's customer somebody else's
        account - which is the exact bug the argument exists to prevent.
        """
        wanted = None if reseller_id is None else str(reseller_id)
        return next(
            (
                u
                for u in self.items.values()
                if u.telegram_id == telegram_id and u.reseller_id == wanted
            ),
            None,
        )

    async def get_by_referral_code(self, code: str) -> User | None:
        return next((u for u in self.items.values() if u.referral_code == code), None)

    async def add(self, user: User) -> None:
        self.items[user.id] = user

    async def update(self, user: User) -> None:
        self.items[user.id] = user


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Admin] = {}

    async def get(self, admin_id: uuid.UUID) -> Admin | None:
        return self.items.get(admin_id)

    async def get_by_username(self, username: str) -> Admin | None:
        return next((a for a in self.items.values() if a.username == username.lower()), None)

    async def get_by_telegram_id(self, telegram_id: int) -> Admin | None:
        return next((a for a in self.items.values() if a.telegram_id == telegram_id), None)

    async def add(self, admin: Admin) -> None:
        self.items[admin.id] = admin

    async def update(self, admin: Admin) -> None:
        self.items[admin.id] = admin

    async def count(self) -> int:
        return len(self.items)


class InMemorySessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, Session] = {}
        self.tokens: dict[uuid.UUID, RefreshToken] = {}

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return self.sessions.get(session_id)

    async def add(self, session: Session) -> None:
        self.sessions[session.id] = session

    async def update(self, session: Session) -> None:
        self.sessions[session.id] = session

    async def list_active_for_subject(
        self, subject_id: uuid.UUID, *, subject_type: SubjectType, now: datetime
    ) -> Sequence[Session]:
        return [
            s
            for s in self.sessions.values()
            if s.subject_id == subject_id
            and s.subject_type is subject_type
            and s.is_active(now=now)
        ]

    async def revoke_all_for_subject(
        self,
        subject_id: uuid.UUID,
        *,
        subject_type: SubjectType,
        reason: RevocationReason,
        now: datetime,
        except_session_id: uuid.UUID | None = None,
    ) -> int:
        count = 0
        for session in self.sessions.values():
            if session.subject_id != subject_id or session.is_revoked:
                continue
            if session.subject_type is not subject_type:
                continue
            if except_session_id is not None and session.id == except_session_id:
                continue
            session.revoke(reason=reason, now=now)
            count += 1
            await self.revoke_refresh_tokens_for_session(session.id, now=now)
        return count

    async def add_refresh_token(self, token: RefreshToken) -> None:
        self.tokens[token.id] = token

    async def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self.tokens.values() if t.token_hash == token_hash), None)

    async def mark_refresh_token_used(
        self, token_id: uuid.UUID, *, replaced_by_id: uuid.UUID, now: datetime
    ) -> bool:
        token = self.tokens.get(token_id)
        if token is None or token.used_at is not None:
            return False
        self.tokens[token_id] = _replace_token(token, used_at=now, replaced_by_id=replaced_by_id)
        return True

    async def revoke_refresh_tokens_for_session(
        self, session_id: uuid.UUID, *, now: datetime
    ) -> int:
        count = 0
        for token_id, token in list(self.tokens.items()):
            if token.session_id != session_id or token.revoked_at is not None:
                continue
            self.tokens[token_id] = _replace_token(token, revoked_at=now)
            count += 1
        return count

    async def delete_expired(self, *, now: datetime) -> int:
        expired = [t_id for t_id, t in self.tokens.items() if t.expires_at < now]
        for token_id in expired:
            del self.tokens[token_id]
        return len(expired)


def _replace_token(token: RefreshToken, **changes: Any) -> RefreshToken:
    """`RefreshToken` is frozen on purpose; replace it rather than mutate it."""
    fields = {
        "id": token.id,
        "session_id": token.session_id,
        "token_hash": token.token_hash,
        "issued_at": token.issued_at,
        "expires_at": token.expires_at,
        "used_at": token.used_at,
        "revoked_at": token.revoked_at,
        "replaced_by_id": token.replaced_by_id,
    }
    fields.update(changes)
    return RefreshToken(**fields)  # type: ignore[arg-type]


class RecordingAudit:
    """Captures audit calls so tests can assert on the security trail itself."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

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
        self.entries.append(
            {
                "action": action,
                "outcome": outcome,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "target_id": target_id,
                "metadata": metadata,
            }
        )

    def actions(self) -> list[AuditAction]:
        return [entry["action"] for entry in self.entries]


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def add(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def search(self, **_: Any) -> Sequence[AuditEntry]:
        return list(self.entries)


class InMemoryRevocationList:
    def __init__(self) -> None:
        self.revoked_sessions: set[uuid.UUID] = set()
        self.revoked_subjects: dict[uuid.UUID, datetime] = {}

    async def revoke_session(self, session_id: uuid.UUID, *, ttl_seconds: int) -> None:
        self.revoked_sessions.add(session_id)

    async def revoke_subject(
        self, subject_id: uuid.UUID, *, at: datetime, ttl_seconds: int
    ) -> None:
        self.revoked_subjects[subject_id] = at

    async def is_revoked(
        self, *, session_id: uuid.UUID, subject_id: uuid.UUID, issued_at: datetime
    ) -> bool:
        if session_id in self.revoked_sessions:
            return True
        epoch = self.revoked_subjects.get(subject_id)
        return epoch is not None and issued_at < epoch


class AllowingRateLimiter:
    def __init__(self, *, allowed: bool = True) -> None:
        self._allowed = allowed
        self.hits: list[str] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitVerdict:
        self.hits.append(key)
        return RateLimitVerdict(
            allowed=self._allowed,
            remaining=limit if self._allowed else 0,
            retry_after_seconds=0 if self._allowed else window_seconds,
        )

    async def reset(self, key: str) -> None:
        self.hits.clear()


class InMemorySettingsStore:
    def __init__(self) -> None:
        self.items: dict[str, SettingRecord] = {}

    async def get(self, key: str) -> SettingRecord | None:
        return self.items.get(key)

    async def all(self) -> Sequence[SettingRecord]:
        return list(self.items.values())

    async def set(
        self,
        key: str,
        value: Any,
        *,
        updated_by: uuid.UUID | None = None,
        description: str | None = None,
        is_secret: bool = False,
    ) -> SettingRecord:
        record = SettingRecord(
            key=key,
            value=value,
            description=description,
            is_secret=is_secret,
            updated_by=updated_by,
        )
        self.items[key] = record
        return record

    async def delete(self, key: str) -> bool:
        return self.items.pop(key, None) is not None


class _EmptyResult:
    """A query that found nothing, in whichever shape the caller unwraps it."""

    rowcount = 0

    def scalar_one_or_none(self) -> None:
        return None

    def scalar(self) -> None:
        return None

    def first(self) -> None:
        return None

    def one_or_none(self) -> None:
        return None

    def all(self) -> list[Any]:
        return []

    def scalars(self) -> _EmptyResult:
        return self


class FakeAsyncSession:
    """Persistence that is reachable but permanently empty.

    The API integration tests assert what a request is *refused* for, and a
    refusal must not depend on Postgres being up. Behaviour that needs a real
    row belongs in the repository tests, which run against a real database.
    """

    async def execute(self, *_args: Any, **_kwargs: Any) -> _EmptyResult:
        return _EmptyResult()

    async def get(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...

    async def delete(self, _obj: Any) -> None: ...

    def add(self, _obj: Any) -> None: ...
