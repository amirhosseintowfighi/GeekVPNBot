"""Authenticate a Telegram user (Mini App, Login Widget, or the bot itself).

This is the only door customers come through, so it does four things and
nothing else: prove the identity, find or create the user, check they are
allowed in, issue tokens.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geekvpn.application.identity.dto import (
    AuthenticationResult,
    RequestContext,
    UserProfile,
)
from geekvpn.application.identity.referral import generate_referral_code
from geekvpn.application.identity.session_service import SessionService
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.repositories import UserRepository
from geekvpn.application.ports.telegram_auth import TelegramAuthVerifier, TelegramIdentity
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.identity.enums import Language, SubjectType
from geekvpn.domain.identity.user import User

_START_PARAM_REFERRAL_PREFIX = "ref_"


class AuthenticateTelegramUser:
    def __init__(
        self,
        *,
        users: UserRepository,
        verifier: TelegramAuthVerifier,
        sessions: SessionService,
        clock: Clock,
        audit: AuditRecorder,
    ) -> None:
        self._users = users
        self._verifier = verifier
        self._sessions = sessions
        self._clock = clock
        self._audit = audit

    async def from_mini_app(
        self, init_data: str, *, context: RequestContext
    ) -> AuthenticationResult:
        return await self._authenticate(self._verifier.verify_mini_app(init_data), context)

    async def from_login_widget(
        self, payload: dict[str, str], *, context: RequestContext
    ) -> AuthenticationResult:
        return await self._authenticate(self._verifier.verify_login_widget(payload), context)

    async def from_trusted_bot_update(
        self, identity: TelegramIdentity, *, context: RequestContext
    ) -> AuthenticationResult:
        """For the bot process.

        The webhook secret token has already proven the update came from
        Telegram, so there is no second signature to check here. This method is
        never reachable from the public API - only the bot container calls it.
        """
        return await self._authenticate(identity, context)

    async def _authenticate(
        self, identity: TelegramIdentity, context: RequestContext
    ) -> AuthenticationResult:
        now = self._clock.now()
        user = await self._users.get_by_telegram_id(identity.telegram_id)
        is_new = user is None

        if user is None:
            user = await self._create(identity, now=now)
        else:
            changed = user.refresh_profile(
                username=identity.username,
                first_name=identity.first_name,
                last_name=identity.last_name,
                language=_language_of(identity.language_code),
                is_premium=identity.is_premium,
                photo_url=identity.photo_url,
            )
            user.ensure_can_authenticate()
            if changed:
                await self._users.update(user)

        user.mark_authenticated(method=identity.method, now=now)
        await self._users.update(user)

        tokens = await self._sessions.issue_pair(
            subject_type=SubjectType.USER,
            subject_id=user.id,
            method=identity.method,
            context=context,
        )
        await self._audit.record(
            AuditAction.AUTH_LOGIN_SUCCEEDED,
            actor_type=SubjectType.USER,
            actor_id=user.id,
            actor_label=user.display_name,
            ip=context.ip,
            user_agent=context.user_agent,
            method=identity.method.value,
            is_new_user=is_new,
        )
        return AuthenticationResult(
            tokens=tokens,
            subject_type=SubjectType.USER,
            method=identity.method,
            user=_to_profile(user),
            is_new_user=is_new,
        )

    async def _create(self, identity: TelegramIdentity, *, now: datetime) -> User:
        referral_code = await self._unique_referral_code()
        user = User.register(
            user_id=uuid.uuid4(),
            telegram_id=identity.telegram_id,
            referral_code=referral_code,
            username=identity.username,
            first_name=identity.first_name,
            last_name=identity.last_name,
            language=_language_of(identity.language_code) or Language.FA,
            is_premium=identity.is_premium,
            photo_url=identity.photo_url,
            referred_by_code=_referral_from_start_param(identity.start_param),
            now=now,
        )
        await self._users.add(user)
        await self._audit.record(
            AuditAction.USER_REGISTERED,
            actor_type=SubjectType.USER,
            actor_id=user.id,
            actor_label=user.display_name,
            telegram_id=identity.telegram_id,
            referred_by_code=user.referred_by_code,
        )
        return user

    async def _unique_referral_code(self, *, attempts: int = 8) -> str:
        """Collision-check the code instead of trusting entropy blindly.

        The code is short because it goes in a `t.me` deep link that people
        read out loud, and short codes collide.
        """
        for _ in range(attempts):
            candidate = generate_referral_code()
            if await self._users.get_by_referral_code(candidate) is None:
                return candidate
        return generate_referral_code(length=12)


def _language_of(code: str | None) -> Language | None:
    if not code:
        return None
    return Language.FA if code.lower().startswith("fa") else Language.EN


def _referral_from_start_param(start_param: str | None) -> str | None:
    if not start_param or not start_param.startswith(_START_PARAM_REFERRAL_PREFIX):
        return None
    code = start_param[len(_START_PARAM_REFERRAL_PREFIX) :].strip().upper()
    return code or None


def _to_profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        telegram_id=user.telegram_id,
        display_name=user.display_name,
        username=user.username,
        language=user.language,
        status=user.status.value,
        referral_code=user.referral_code,
        is_premium=user.is_premium,
        photo_url=user.photo_url,
        created_at=user.created_at,
    )
