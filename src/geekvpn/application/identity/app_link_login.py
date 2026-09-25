"""Sign the Android app in by approving it inside the bot.

    app                     API                          bot (Telegram)
    ---                     ---                          --------------
    start ----------------> request (pending), code,
                            poll token
    opens t.me/<bot>?start=applogin_<code> ----------->  claim(code) binds the
                                                         request to this account,
                                                         shows approve / cancel
    poll(poll token) -----> pending ...                  decide(approve)
    poll(poll token) -----> approved: issue a session,
                            mark consumed, return tokens

The session comes from the same `SessionService` and customer policy as every
other customer login, so refresh, rotation, reuse detection, logout and the
session list all work for the app without a line of their own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import structlog

from geekvpn.application.identity.authenticate_telegram import to_profile
from geekvpn.application.identity.dto import AuthenticationResult, RequestContext
from geekvpn.application.identity.session_service import SessionService
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.application.ports.rate_limiter import RateLimiter
from geekvpn.application.ports.repositories import (
    AppLoginRepository,
    SessionRepository,
    UserRepository,
)
from geekvpn.application.ports.tokens import RefreshTokenFactory
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import RateLimitedError, ValidationError
from geekvpn.domain.identity.app_login import AppLoginRequest, AppLoginStatus
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    AppLoginAlreadyUsedError,
    AppLoginExpiredError,
    AppLoginNotFoundError,
    AppLoginNotYoursError,
)
from geekvpn.domain.identity.session import RevocationReason

logger = structlog.stdlib.get_logger(__name__)

#: What goes in front of the code in the deep link's start parameter. The bot's
#: /start handler checks for it before the referral prefix.
START_PARAM_PREFIX = "applogin_"

#: Five minutes: long enough to switch to Telegram and back on a slow phone,
#: short enough that a link left in a chat history is dead by the time anyone
#: scrolls up to it.
REQUEST_TTL = timedelta(minutes=5)

#: Per IP and per device, in `START_RATE_WINDOW_SECONDS`. A person retrying a
#: sign-in a few times is normal; a hundred requests is somebody filling the
#: table or spamming a victim's chat with approval prompts.
START_LIMIT_PER_IP = 20
START_LIMIT_PER_DEVICE = 5
START_RATE_WINDOW_SECONDS = 600

#: Sessions the Android app holds, however it signed in. The bot's device list
#: shows these and only these.
APP_AUTH_METHODS = frozenset({AuthMethod.TELEGRAM_APP_LINK, AuthMethod.APP_PASSWORD})

_MAX_DEVICE_ID = 64
_MAX_DEVICE_NAME = 64
_MAX_PLATFORM = 16
_MAX_APP_VERSION = 32


@dataclass(frozen=True, slots=True)
class AppLinkStarted:
    request_id: uuid.UUID
    #: Goes in the deep link. Shown to nobody else by the API.
    code: str
    #: Stays in the app. The only way to collect the tokens.
    poll_token: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class AppLinkPoll:
    """What the app sees. Tokens only when `status` is approved."""

    status: AppLoginStatus
    result: AuthenticationResult | None = None


@dataclass(frozen=True, slots=True)
class AppDevice:
    """A phone signed in through the app, as the bot's device list shows it."""

    session_id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime


class AppLinkLogin:
    def __init__(
        self,
        *,
        requests: AppLoginRepository,
        users: UserRepository,
        sessions: SessionService,
        session_records: SessionRepository,
        secrets: RefreshTokenFactory,
        rate_limiter: RateLimiter,
        clock: Clock,
        audit: AuditRecorder,
    ) -> None:
        self._requests = requests
        self._users = users
        self._sessions = sessions
        self._session_records = session_records
        self._secrets = secrets
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._audit = audit

    # -- app side ------------------------------------------------------------

    async def start(
        self,
        *,
        device_id: str,
        device_name: str,
        platform: str,
        app_version: str,
        context: RequestContext,
    ) -> AppLinkStarted:
        device_id = _required(device_id, "device_id", _MAX_DEVICE_ID)
        await self._enforce_rate_limit(device_id=device_id, ip=context.ip)

        code, code_hash = self._secrets.generate()
        poll_token, poll_token_hash = self._secrets.generate()
        now = self._clock.now()
        request = AppLoginRequest(
            id=uuid.uuid4(),
            code_hash=code_hash,
            poll_token_hash=poll_token_hash,
            device_id=device_id,
            device_name=_clip(device_name, _MAX_DEVICE_NAME) or "Android",
            platform=_clip(platform, _MAX_PLATFORM) or "android",
            app_version=_clip(app_version, _MAX_APP_VERSION),
            ip=context.ip,
            status=AppLoginStatus.PENDING,
            created_at=now,
            expires_at=now + REQUEST_TTL,
        )
        await self._requests.add(request)
        logger.info("app_login.started", request_id=str(request.id), platform=request.platform)
        return AppLinkStarted(
            request_id=request.id,
            code=code,
            poll_token=poll_token,
            expires_in_seconds=int(REQUEST_TTL.total_seconds()),
        )

    async def poll(self, poll_token: str, *, context: RequestContext) -> AppLinkPoll:
        """One look at the request. Long-polling is the caller's loop.

        Kept to a single check so the waiting happens outside any database
        transaction: a connection held open for 25 seconds per phone would
        drain the pool long before the server ran out of anything else.
        """
        request = await self._requests.get_by_poll_token_hash(self._secrets.hash(poll_token))
        if request is None:
            raise AppLoginNotFoundError()

        now = self._clock.now()
        status = request.status_at(now)
        if status is AppLoginStatus.CONSUMED:
            # Tokens are handed out once. A second poll - a retry after a
            # dropped response, or somebody else holding the poll token - gets
            # nothing, and reads the same as a request that ran out of time.
            return AppLinkPoll(status=AppLoginStatus.EXPIRED)
        if status is not AppLoginStatus.APPROVED:
            return AppLinkPoll(status=status)

        if not await self._requests.consume(request.id, now=now):
            # Lost the race to a concurrent poll with the same token.
            return AppLinkPoll(status=AppLoginStatus.EXPIRED)
        return AppLinkPoll(
            status=AppLoginStatus.APPROVED,
            result=await self._sign_in(request, context=context),
        )

    # -- bot side ------------------------------------------------------------

    async def claim(self, code: str, *, telegram_user_id: int) -> AppLoginRequest:
        """The link was opened in Telegram by `telegram_user_id`.

        The first account to open it owns it. A second open - the same person
        tapping the link again, or anyone the link was forwarded to - is
        refused, so the approve button only ever exists in one chat.
        """
        request = await self._requests.get_by_code_hash(self._secrets.hash(code))
        if request is None:
            raise AppLoginNotFoundError()
        now = self._clock.now()
        self._ensure_open(request, now=now)
        if request.telegram_user_id is not None:
            raise AppLoginAlreadyUsedError()
        if not await self._requests.claim(request.id, telegram_user_id=telegram_user_id, now=now):
            raise AppLoginAlreadyUsedError()
        logger.info("app_login.claimed", request_id=str(request.id))
        return replace(request, telegram_user_id=telegram_user_id)

    async def decide(
        self, request_id: uuid.UUID, *, telegram_user_id: int, approve: bool
    ) -> AppLoginStatus:
        """Approve or deny, from the buttons under the bot's prompt.

        Only the account the prompt was sent to may press them. Telegram's
        callback data is not a secret - a client can send any `request_id` it
        likes - so the check is against the claim, not against who can see
        the message.
        """
        request = await self._requests.get(request_id)
        if request is None:
            raise AppLoginNotFoundError()
        if request.telegram_user_id != telegram_user_id:
            raise AppLoginNotYoursError()
        now = self._clock.now()
        self._ensure_open(request, now=now)

        status = AppLoginStatus.APPROVED if approve else AppLoginStatus.DENIED
        if not await self._requests.decide(
            request.id, telegram_user_id=telegram_user_id, status=status, now=now
        ):
            raise AppLoginAlreadyUsedError()
        logger.info("app_login.decided", request_id=str(request.id), status=status.value)
        return status

    # -- the customer's devices (bot) ----------------------------------------

    async def devices(self, user_id: uuid.UUID) -> list[AppDevice]:
        """Live app sessions, most recently used first.

        Only sessions the app created. The Mini App and the bot do not keep
        sessions a customer would recognise as "a device", and listing them
        would invite someone to cut off the chat they are reading this in.
        """
        sessions = await self._session_records.list_active_for_subject(
            user_id, subject_type=SubjectType.USER, now=self._clock.now()
        )
        return [
            AppDevice(
                session_id=session.id,
                name=session.device.label or "Android",
                created_at=session.created_at,
                last_used_at=session.last_used_at,
            )
            for session in sessions
            if session.auth_method in APP_AUTH_METHODS
        ]

    async def disconnect(self, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
        """Sign one device out. False when it is not this customer's app session.

        The session id arrives in callback data, which a client can forge, so
        ownership is checked against the stored session rather than assumed
        from the button having been shown.
        """
        session = await self._session_records.get(session_id)
        if (
            session is None
            or session.subject_type is not SubjectType.USER
            or session.subject_id != user_id
            or session.auth_method not in APP_AUTH_METHODS
        ):
            return False
        await self._sessions.revoke(session_id, reason=RevocationReason.LOGOUT)
        return True

    # -- internals -----------------------------------------------------------

    def _ensure_open(self, request: AppLoginRequest, *, now: datetime) -> None:
        status = request.status_at(now)
        if status is AppLoginStatus.EXPIRED:
            raise AppLoginExpiredError()
        if status is not AppLoginStatus.PENDING:
            raise AppLoginAlreadyUsedError()

    async def _sign_in(
        self, request: AppLoginRequest, *, context: RequestContext
    ) -> AuthenticationResult:
        if request.telegram_user_id is None:  # pragma: no cover - approve requires a claim
            raise AppLoginNotFoundError()
        # The platform's own shop. The app is GeekVPN's, and a reseller's bot
        # never claims a request (the handler refuses there).
        user = await self._users.get_by_telegram_id(request.telegram_user_id, reseller_id=None)
        if user is None:
            # Approval happens in a chat whose update already created the
            # account, so this is a deleted account, not a new one.
            raise AppLoginNotFoundError()

        now = self._clock.now()
        user.mark_authenticated(method=AuthMethod.TELEGRAM_APP_LINK, now=now)
        await self._users.update(user)

        # The session list shows the phone's own name, not the HTTP client.
        session_context = RequestContext(
            ip=context.ip,
            user_agent=f"GeekVPN/{request.app_version} ({request.platform})",
            device_label=request.device_name,
        )
        tokens = await self._sessions.issue_pair(
            subject_type=SubjectType.USER,
            subject_id=user.id,
            method=AuthMethod.TELEGRAM_APP_LINK,
            context=session_context,
        )
        await self._audit.record(
            AuditAction.AUTH_LOGIN_SUCCEEDED,
            actor_type=SubjectType.USER,
            actor_id=user.id,
            actor_label=user.display_name,
            ip=context.ip,
            user_agent=session_context.user_agent,
            method=AuthMethod.TELEGRAM_APP_LINK.value,
            is_new_user=False,
        )
        return AuthenticationResult(
            tokens=tokens,
            subject_type=SubjectType.USER,
            method=AuthMethod.TELEGRAM_APP_LINK,
            user=to_profile(user),
        )

    async def _enforce_rate_limit(self, *, device_id: str, ip: str | None) -> None:
        checks = [(f"app-login:device:{device_id}", START_LIMIT_PER_DEVICE)]
        if ip:
            checks.append((f"app-login:ip:{ip}", START_LIMIT_PER_IP))
        for key, limit in checks:
            verdict = await self._rate_limiter.hit(
                key, limit=limit, window_seconds=START_RATE_WINDOW_SECONDS
            )
            if not verdict.allowed:
                raise RateLimitedError()


def _clip(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


def _required(value: str | None, field: str, limit: int) -> str:
    cleaned = _clip(value, limit)
    if not cleaned:
        raise ValidationError(f"{field} is required.")
    return cleaned
