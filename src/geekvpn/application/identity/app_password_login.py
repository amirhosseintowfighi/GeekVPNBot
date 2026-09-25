"""Sign the Android app in with a username and password.

The customer chooses both inside the bot (profile, "ورود با نام کاربری"), so
every password belongs to an account Telegram already vouched for; the app
never creates accounts this way. The session is an ordinary customer session
from `SessionService`, like `AppLinkLogin`'s, so refresh, logout and the bot's
device list work unchanged.

Guessing is made expensive three ways, the same as the admin login: Argon2id
per attempt, a rate limit per username and per IP, and a dummy verification
for unknown usernames so the response time does not reveal which exist.
"""

from __future__ import annotations

import contextlib
import secrets
import uuid
from dataclasses import dataclass

import structlog

from geekvpn.application.identity.authenticate_telegram import to_profile
from geekvpn.application.identity.dto import AuthenticationResult, RequestContext
from geekvpn.application.identity.session_service import SessionService
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.passwords import PasswordHasher
from geekvpn.application.ports.rate_limiter import RateLimiter
from geekvpn.application.ports.repositories import (
    AppCredentialRepository,
    SessionRepository,
    UserRepository,
)
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.base.errors import RateLimitedError
from geekvpn.domain.identity.app_credentials import (
    PASSWORD_MAX,
    AppCredential,
    check_password,
    normalize_username,
)
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    AppUsernameInvalidError,
    AppUsernameTakenError,
    InvalidCredentialsError,
)
from geekvpn.domain.identity.session import RevocationReason

logger = structlog.stdlib.get_logger(__name__)

#: Per username: a person mistyping a few times is fine, a dictionary is not.
LOGIN_LIMIT_PER_USERNAME = 10
#: Per IP. Looser, because Iranian mobile carriers put many phones behind one
#: address (CGNAT) - the per-username limit is the one that stops guessing.
LOGIN_LIMIT_PER_IP = 30
LOGIN_RATE_WINDOW_SECONDS = 900

_MAX_DEVICE_NAME = 64
_MAX_PLATFORM = 16
_MAX_APP_VERSION = 32


@dataclass(frozen=True, slots=True)
class AppLoginDevice:
    """What the app says about itself; shown in the bot's device list."""

    name: str = ""
    platform: str = "android"
    app_version: str = ""


class AppPasswordLogin:
    def __init__(
        self,
        *,
        credentials: AppCredentialRepository,
        users: UserRepository,
        passwords: PasswordHasher,
        sessions: SessionService,
        session_records: SessionRepository,
        rate_limiter: RateLimiter,
        clock: Clock,
        audit: AuditRecorder,
    ) -> None:
        self._credentials = credentials
        self._users = users
        self._passwords = passwords
        self._sessions = sessions
        self._session_records = session_records
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._audit = audit
        self._dummy_hash: str | None = None

    # -- bot side --------------------------------------------------------------

    async def username_of(self, user_id: uuid.UUID) -> str | None:
        credential = await self._credentials.get_by_user(user_id)
        return credential.username if credential is not None else None

    async def is_available(self, username: str, *, user_id: uuid.UUID) -> str:
        """Validate and normalise a wanted username; raise when someone else has it.

        Asked before the password so the customer does not type a password
        for a name they cannot have. `set_credentials` checks again.
        """
        normalized = normalize_username(username)
        holder = await self._credentials.get_by_username(normalized)
        if holder is not None and holder.user_id != user_id:
            raise AppUsernameTakenError()
        return normalized

    async def set_credentials(self, user_id: uuid.UUID, *, username: str, password: str) -> str:
        """Set or replace this customer's app login. Returns the stored username.

        Replacing it signs out every phone that used the old password: a
        customer changes a password because someone else may know it.
        """
        user = await self._users.get(user_id)
        if user is None or user.reseller_id is not None:
            # The app is the platform's; a reseller's customer is a different
            # account with its own wallet and services.
            raise AppUsernameInvalidError()
        normalized = await self.is_available(username, user_id=user.id)
        check_password(password, username=normalized)

        credential = AppCredential(
            user_id=user.id,
            username=normalized,
            password_hash=self._passwords.hash(password),
            updated_at=self._clock.now(),
        )
        if not await self._credentials.save(credential):
            raise AppUsernameTakenError()
        await self._sign_out_password_sessions(user.id)
        await self._audit.record(
            AuditAction.USER_APP_PASSWORD_CHANGED,
            actor_type=SubjectType.USER,
            actor_id=user.id,
            actor_label=user.display_name,
            method=AuthMethod.APP_PASSWORD.value,
        )
        return normalized

    async def remove_credentials(self, user_id: uuid.UUID) -> bool:
        removed = await self._credentials.delete(user_id)
        if removed:
            await self._sign_out_password_sessions(user_id)
            await self._audit.record(
                AuditAction.USER_APP_PASSWORD_REMOVED,
                actor_type=SubjectType.USER,
                actor_id=user_id,
                method=AuthMethod.APP_PASSWORD.value,
            )
        return removed

    # -- app side --------------------------------------------------------------

    async def login(
        self,
        *,
        username: str,
        password: str,
        device: AppLoginDevice,
        context: RequestContext,
    ) -> AuthenticationResult:
        key = username.strip().lower()[:64]
        await self._enforce_rate_limit(username=key, ip=context.ip)

        credential = None
        # A name that could never have been set is simply unknown.
        with contextlib.suppress(AppUsernameInvalidError):
            credential = await self._credentials.get_by_username(normalize_username(key))
        # Over-long input is refused before hashing it, so it cannot be used
        # to make each attempt expensive for us rather than for the guesser.
        if len(password) > PASSWORD_MAX:
            password = ""

        if credential is None:
            self._dummy_verify(password)
            await self._fail(key, context, reason="unknown_username")
            raise InvalidCredentialsError()
        if not password or not self._passwords.verify(password, credential.password_hash):
            await self._fail(key, context, reason="bad_password", user_id=credential.user_id)
            raise InvalidCredentialsError()

        user = await self._users.get(credential.user_id)
        if user is None or user.reseller_id is not None:
            await self._fail(key, context, reason="no_account", user_id=credential.user_id)
            raise InvalidCredentialsError()

        now = self._clock.now()
        user.mark_authenticated(method=AuthMethod.APP_PASSWORD, now=now)  # raises when suspended
        await self._users.update(user)

        if self._passwords.needs_rehash(credential.password_hash):
            await self._credentials.save(
                AppCredential(
                    user_id=user.id,
                    username=credential.username,
                    password_hash=self._passwords.hash(password),
                    updated_at=now,
                )
            )

        session_context = RequestContext(
            ip=context.ip,
            user_agent=(
                f"GeekVPN/{_clip(device.app_version, _MAX_APP_VERSION)} "
                f"({_clip(device.platform, _MAX_PLATFORM) or 'android'})"
            ),
            device_label=_clip(device.name, _MAX_DEVICE_NAME) or "Android",
        )
        tokens = await self._sessions.issue_pair(
            subject_type=SubjectType.USER,
            subject_id=user.id,
            method=AuthMethod.APP_PASSWORD,
            context=session_context,
        )
        await self._audit.record(
            AuditAction.AUTH_LOGIN_SUCCEEDED,
            actor_type=SubjectType.USER,
            actor_id=user.id,
            actor_label=user.display_name,
            ip=context.ip,
            user_agent=session_context.user_agent,
            method=AuthMethod.APP_PASSWORD.value,
            is_new_user=False,
        )
        return AuthenticationResult(
            tokens=tokens,
            subject_type=SubjectType.USER,
            method=AuthMethod.APP_PASSWORD,
            user=to_profile(user),
        )

    # -- internals ---------------------------------------------------------------

    def _dummy_verify(self, password: str) -> None:
        """Spend a real Argon2 verification on an unknown username.

        Otherwise "no such username" answers in microseconds and a wrong
        password in a quarter second, and the endpoint tells anyone which
        usernames exist. Built lazily: hashing costs 64 MiB and the bot's
        scope builds this service on every update.
        """
        if self._dummy_hash is None:
            self._dummy_hash = self._passwords.hash(secrets.token_urlsafe(32))
        self._passwords.verify(password or "x", self._dummy_hash)

    async def _sign_out_password_sessions(self, user_id: uuid.UUID) -> None:
        sessions = await self._session_records.list_active_for_subject(
            user_id, subject_type=SubjectType.USER, now=self._clock.now()
        )
        for session in sessions:
            if session.auth_method is AuthMethod.APP_PASSWORD:
                await self._sessions.revoke(session.id, reason=RevocationReason.LOGOUT)

    async def _enforce_rate_limit(self, *, username: str, ip: str | None) -> None:
        checks = [(f"app-password:user:{username}", LOGIN_LIMIT_PER_USERNAME)]
        if ip:
            checks.append((f"app-password:ip:{ip}", LOGIN_LIMIT_PER_IP))
        for key, limit in checks:
            verdict = await self._rate_limiter.hit(
                key, limit=limit, window_seconds=LOGIN_RATE_WINDOW_SECONDS
            )
            if not verdict.allowed:
                raise RateLimitedError()

    async def _fail(
        self,
        username: str,
        context: RequestContext,
        *,
        reason: str,
        user_id: uuid.UUID | None = None,
    ) -> None:
        logger.info("app_password.login_failed", reason=reason)
        await self._audit.record(
            AuditAction.AUTH_LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            actor_type=SubjectType.USER,
            actor_id=user_id,
            actor_label=username,
            ip=context.ip,
            user_agent=context.user_agent,
            method=AuthMethod.APP_PASSWORD.value,
            reason=reason,
        )


def _clip(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]
