"""Session issuing, rotation and revocation.

Every authentication path in the system funnels through `issue_pair`, and every
renewal through `rotate`. Keeping this in exactly one place is what guarantees
that the bot, the Mini App and the admin panel cannot drift apart on something
as security-critical as token lifetime.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from geekvpn.application.identity.dto import RequestContext, TokenPair
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.repositories import SessionRepository
from geekvpn.application.ports.revocation import RevocationList
from geekvpn.application.ports.tokens import AccessTokenService, RefreshTokenFactory
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    SessionRevokedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenReuseDetectedError,
)
from geekvpn.domain.identity.session import (
    DeviceInfo,
    RefreshToken,
    RevocationReason,
    Session,
)

#: A callable answering "what may this subject do right now?" at refresh time,
#: so a permission change takes effect on the next refresh instead of being
#: frozen into the session forever.
RoleResolver = Callable[[SubjectType, uuid.UUID], Awaitable[tuple[str | None, tuple[str, ...]]]]


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """Lifetimes, resolved from settings at composition time.

    Different subjects get different policies: an admin session is short
    because an admin can move money; a customer session is long because making
    someone re-authenticate to check their remaining traffic is hostile.
    """

    refresh_ttl: timedelta
    absolute_ttl: timedelta


@dataclass(frozen=True, slots=True)
class RotationOutcome:
    tokens: TokenPair
    session: Session


class SessionService:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        access_tokens: AccessTokenService,
        refresh_tokens: RefreshTokenFactory,
        clock: Clock,
        audit: AuditRecorder,
        revocations: RevocationList,
        user_policy: SessionPolicy,
        admin_policy: SessionPolicy,
        access_ttl_seconds: int,
    ) -> None:
        self._sessions = sessions
        self._access = access_tokens
        self._refresh = refresh_tokens
        self._clock = clock
        self._audit = audit
        self._revocations = revocations
        self._user_policy = user_policy
        self._admin_policy = admin_policy
        # Revocation entries only need to outlive the longest access token
        # that could still be in flight.
        self._revocation_ttl = access_ttl_seconds + 60

    def policy_for(self, subject_type: SubjectType) -> SessionPolicy:
        return self._admin_policy if subject_type is SubjectType.ADMIN else self._user_policy

    # -- issue -------------------------------------------------------------

    async def issue_pair(
        self,
        *,
        subject_type: SubjectType,
        subject_id: uuid.UUID,
        method: AuthMethod,
        context: RequestContext,
        role: str | None = None,
        permissions: tuple[str, ...] = (),
    ) -> TokenPair:
        now = self._clock.now()
        policy = self.policy_for(subject_type)

        session = Session(
            uuid.uuid4(),
            subject_type=subject_type,
            subject_id=subject_id,
            auth_method=method,
            created_at=now,
            absolute_expires_at=now + policy.absolute_ttl,
            device=DeviceInfo(
                ip=context.ip,
                user_agent=context.user_agent,
                label=context.device_label,
            ),
        )
        await self._sessions.add(session)

        return await self._mint(
            session=session, now=now, policy=policy, role=role, permissions=permissions
        )

    async def _mint(
        self,
        *,
        session: Session,
        now: datetime,
        policy: SessionPolicy,
        role: str | None,
        permissions: tuple[str, ...],
        token_id: uuid.UUID | None = None,
    ) -> TokenPair:
        """Create one access/refresh pair for an already-persisted session.

        `token_id` must be supplied by `rotate`, which pre-allocates the id so
        the outgoing token's `replaced_by_id` points at a row that actually
        exists. Without it the rotation chain dangles and forensic replay of a
        stolen-token incident becomes impossible.
        """
        access = self._access.issue(
            subject_type=session.subject_type,
            subject_id=session.subject_id,
            session_id=session.id,
            role=role,
            permissions=permissions,
        )
        plaintext, token_hash = self._refresh.generate()

        # A refresh token never outlives the session's absolute cap.
        refresh_expires_at = min(now + policy.refresh_ttl, session.absolute_expires_at)
        record = RefreshToken(
            id=token_id if token_id is not None else uuid.uuid4(),
            session_id=session.id,
            token_hash=token_hash,
            issued_at=now,
            expires_at=refresh_expires_at,
        )
        await self._sessions.add_refresh_token(record)

        return TokenPair(
            access_token=access.value,
            access_expires_at=access.expires_at,
            refresh_token=plaintext,
            refresh_expires_at=refresh_expires_at,
            session_id=session.id,
        )

    # -- rotate ------------------------------------------------------------

    async def rotate(
        self,
        *,
        refresh_token: str,
        context: RequestContext,
        role_resolver: RoleResolver,
    ) -> RotationOutcome:
        """Exchange a refresh token for a new pair.

        Reuse of an already-rotated token destroys the entire session. See the
        module docstring of `domain.identity.session` for why.
        """
        now = self._clock.now()
        token_hash = self._refresh.hash(refresh_token)
        stored = await self._sessions.get_refresh_token_by_hash(token_hash)

        if stored is None:
            raise TokenInvalidError()

        session = await self._sessions.get(stored.session_id)
        if session is None:  # pragma: no cover - foreign key makes this impossible
            raise TokenInvalidError()

        if stored.is_spent:
            await self._handle_reuse(session=session, now=now, context=context)
            raise TokenReuseDetectedError()

        if stored.is_expired(now=now):
            raise TokenExpiredError()

        if not session.is_active(now=now):
            raise SessionRevokedError()

        # Claim the old token FIRST, conditionally on it still being unused.
        # Two concurrent refreshes with the same token race here, and exactly
        # one wins - the loser sees zero rows updated and is rejected rather
        # than being handed a second valid session.
        replacement_id = uuid.uuid4()
        claimed = await self._sessions.mark_refresh_token_used(
            stored.id, replaced_by_id=replacement_id, now=now
        )
        if claimed is False:
            raise TokenReuseDetectedError()

        role, permissions = await role_resolver(session.subject_type, session.subject_id)

        session.touch(
            now=now,
            device=DeviceInfo(
                ip=context.ip,
                user_agent=context.user_agent,
                label=session.device.label,
            ),
        )
        await self._sessions.update(session)

        tokens = await self._mint(
            session=session,
            now=now,
            policy=self.policy_for(session.subject_type),
            role=role,
            permissions=permissions,
            token_id=replacement_id,
        )
        await self._audit.record(
            AuditAction.AUTH_TOKEN_REFRESHED,
            actor_type=session.subject_type,
            actor_id=session.subject_id,
            target_type="session",
            target_id=str(session.id),
            ip=context.ip,
            user_agent=context.user_agent,
        )
        return RotationOutcome(tokens=tokens, session=session)

    async def _handle_reuse(
        self, *, session: Session, now: datetime, context: RequestContext
    ) -> None:
        session.revoke(reason=RevocationReason.TOKEN_REUSE, now=now)
        await self._sessions.update(session)
        await self._sessions.revoke_refresh_tokens_for_session(session.id, now=now)
        await self._revocations.revoke_session(session.id, ttl_seconds=self._revocation_ttl)
        await self._audit.record(
            AuditAction.AUTH_TOKEN_REUSE_DETECTED,
            outcome=AuditOutcome.FAILURE,
            actor_type=session.subject_type,
            actor_id=session.subject_id,
            target_type="session",
            target_id=str(session.id),
            ip=context.ip,
            user_agent=context.user_agent,
            original_ip=session.device.ip,
        )

    # -- revoke ------------------------------------------------------------

    async def revoke(
        self,
        session_id: uuid.UUID,
        *,
        reason: RevocationReason = RevocationReason.LOGOUT,
    ) -> None:
        now = self._clock.now()
        session = await self._sessions.get(session_id)
        if session is None or session.is_revoked:
            return
        session.revoke(reason=reason, now=now)
        await self._sessions.update(session)
        await self._sessions.revoke_refresh_tokens_for_session(session_id, now=now)
        await self._revocations.revoke_session(session_id, ttl_seconds=self._revocation_ttl)
        await self._audit.record(
            AuditAction.AUTH_LOGOUT,
            actor_type=session.subject_type,
            actor_id=session.subject_id,
            target_type="session",
            target_id=str(session_id),
            reason=reason.value,
        )

    async def revoke_all(
        self,
        *,
        subject_type: SubjectType,
        subject_id: uuid.UUID,
        reason: RevocationReason = RevocationReason.LOGOUT_ALL,
        except_session_id: uuid.UUID | None = None,
    ) -> int:
        now = self._clock.now()
        count = await self._sessions.revoke_all_for_subject(
            subject_id,
            subject_type=subject_type,
            reason=reason,
            now=now,
            except_session_id=except_session_id,
        )
        if except_session_id is None:
            # Publish an epoch: every access token minted before now is dead.
            await self._revocations.revoke_subject(
                subject_id, at=now, ttl_seconds=self._revocation_ttl
            )
        await self._audit.record(
            AuditAction.AUTH_LOGOUT_ALL,
            actor_type=subject_type,
            actor_id=subject_id,
            revoked_sessions=count,
            reason=reason.value,
        )
        return count
