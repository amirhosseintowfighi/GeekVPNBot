"""Android app sign-in approved in the bot (`AppLinkLogin`)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from tests.fakes import (
    AllowingRateLimiter,
    FrozenClock,
    InMemoryAppLoginRepository,
    InMemoryRevocationList,
    InMemorySessionRepository,
    InMemoryUserRepository,
    RecordingAudit,
)

from geekvpn.application.identity.app_link_login import REQUEST_TTL, AppLinkLogin
from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.identity.session_service import SessionPolicy, SessionService
from geekvpn.domain.base.errors import RateLimitedError, ValidationError
from geekvpn.domain.identity.app_login import AppLoginStatus
from geekvpn.domain.identity.enums import AuthMethod, SubjectType
from geekvpn.domain.identity.errors import (
    AccountSuspendedError,
    AppLoginAlreadyUsedError,
    AppLoginExpiredError,
    AppLoginNotFoundError,
    AppLoginNotYoursError,
)
from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService
from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory

pytestmark = pytest.mark.unit

CONTEXT = RequestContext(ip="5.6.7.8", user_agent="okhttp/5")
OWNER = 555
STRANGER = 999


class World:
    def __init__(self, *, rate_limited: bool = False) -> None:
        self.clock = FrozenClock()
        self.users = InMemoryUserRepository()
        self.requests = InMemoryAppLoginRepository()
        self.session_records = InMemorySessionRepository()
        self.rate_limiter = AllowingRateLimiter(allowed=not rate_limited)
        audit = RecordingAudit()
        self.sessions = SessionService(
            sessions=self.session_records,
            access_tokens=JwtAccessTokenService(
                secret_key="s" * 48,
                issuer="geekvpn",
                audience="geekvpn-clients",
                ttl=timedelta(minutes=15),
            ),
            refresh_tokens=Sha256RefreshTokenFactory(),
            clock=self.clock,
            audit=audit,
            revocations=InMemoryRevocationList(),
            user_policy=SessionPolicy(
                refresh_ttl=timedelta(days=30), absolute_ttl=timedelta(days=180)
            ),
            admin_policy=SessionPolicy(
                refresh_ttl=timedelta(hours=12), absolute_ttl=timedelta(hours=24)
            ),
            access_ttl_seconds=900,
        )
        self.login = AppLinkLogin(
            requests=self.requests,
            users=self.users,
            sessions=self.sessions,
            session_records=self.session_records,
            secrets=Sha256RefreshTokenFactory(),
            rate_limiter=self.rate_limiter,
            clock=self.clock,
            audit=audit,
        )

    async def customer(self, telegram_id: int = OWNER) -> User:
        user = User.register(
            user_id=uuid.uuid4(),
            telegram_id=telegram_id,
            referral_code=f"R{telegram_id}",
            first_name="Amir",
            now=self.clock.now(),
        )
        await self.users.add(user)
        return user

    async def start(self, device_id: str = "dev-1"):
        return await self.login.start(
            device_id=device_id,
            device_name="Pixel 6",
            platform="android",
            app_version="0.1.0",
            context=CONTEXT,
        )


# -- starting ------------------------------------------------------------------


async def test_only_hashes_of_the_code_and_poll_token_are_stored() -> None:
    world = World()
    started = await world.start()

    stored = world.requests.items[started.request_id]
    assert started.code not in (stored.code_hash, stored.poll_token_hash)
    assert started.poll_token not in (stored.code_hash, stored.poll_token_hash)
    assert stored.status is AppLoginStatus.PENDING
    assert stored.expires_at - stored.created_at == REQUEST_TTL
    assert started.expires_in_seconds == 300


async def test_the_code_and_poll_token_are_32_random_bytes_each() -> None:
    started = await World().start()
    # 32 bytes of base64url, unpadded.
    assert len(started.code) == 43
    assert len(started.poll_token) == 43
    assert started.code != started.poll_token


async def test_a_request_without_a_device_id_is_refused() -> None:
    with pytest.raises(ValidationError):
        await World().start(device_id="  ")


async def test_starting_is_rate_limited_per_device_and_per_ip() -> None:
    world = World(rate_limited=True)
    with pytest.raises(RateLimitedError):
        await world.start()
    assert world.requests.items == {}

    allowed = World()
    await allowed.start(device_id="dev-7")
    assert "app-login:device:dev-7" in allowed.rate_limiter.hits
    assert "app-login:ip:5.6.7.8" in allowed.rate_limiter.hits


# -- the happy path ------------------------------------------------------------


async def test_an_approved_request_hands_the_app_a_customer_session_once() -> None:
    world = World()
    user = await world.customer()
    started = await world.start()

    request = await world.login.claim(started.code, telegram_user_id=OWNER)
    assert request.telegram_user_id == OWNER
    pending = await world.login.poll(started.poll_token, context=CONTEXT)
    assert pending.status is AppLoginStatus.PENDING
    assert pending.result is None

    status = await world.login.decide(request.id, telegram_user_id=OWNER, approve=True)
    assert status is AppLoginStatus.APPROVED

    outcome = await world.login.poll(started.poll_token, context=CONTEXT)
    assert outcome.status is AppLoginStatus.APPROVED
    assert outcome.result is not None
    assert outcome.result.user is not None
    assert outcome.result.user.id == user.id
    assert outcome.result.tokens.access_token
    assert outcome.result.tokens.refresh_token

    session = await world.session_records.get(outcome.result.tokens.session_id)
    assert session is not None
    assert session.subject_type is SubjectType.USER
    assert session.auth_method is AuthMethod.TELEGRAM_APP_LINK
    # The session list shows the phone, not the HTTP client.
    assert session.device.label == "Pixel 6"


async def test_a_second_poll_after_the_tokens_were_collected_gets_nothing() -> None:
    world = World()
    await world.customer()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)
    await world.login.decide(request.id, telegram_user_id=OWNER, approve=True)
    first = await world.login.poll(started.poll_token, context=CONTEXT)
    assert first.result is not None

    second = await world.login.poll(started.poll_token, context=CONTEXT)

    assert second.status is AppLoginStatus.EXPIRED
    assert second.result is None
    assert world.requests.items[request.id].status is AppLoginStatus.CONSUMED


# -- refusals ------------------------------------------------------------------


async def test_deny_leaves_the_app_without_tokens() -> None:
    world = World()
    await world.customer()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)

    status = await world.login.decide(request.id, telegram_user_id=OWNER, approve=False)
    outcome = await world.login.poll(started.poll_token, context=CONTEXT)

    assert status is AppLoginStatus.DENIED
    assert outcome.status is AppLoginStatus.DENIED
    assert outcome.result is None
    assert (
        await world.session_records.list_active_for_subject(
            next(iter(world.users.items)), subject_type=SubjectType.USER, now=world.clock.now()
        )
        == []
    )


async def test_a_denied_request_cannot_be_approved_afterwards() -> None:
    world = World()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)
    await world.login.decide(request.id, telegram_user_id=OWNER, approve=False)

    with pytest.raises(AppLoginAlreadyUsedError):
        await world.login.decide(request.id, telegram_user_id=OWNER, approve=True)


async def test_a_code_opened_a_second_time_is_refused() -> None:
    world = World()
    started = await world.start()
    await world.login.claim(started.code, telegram_user_id=OWNER)

    # The same person tapping the link again, and anyone it was forwarded to.
    with pytest.raises(AppLoginAlreadyUsedError):
        await world.login.claim(started.code, telegram_user_id=OWNER)
    with pytest.raises(AppLoginAlreadyUsedError):
        await world.login.claim(started.code, telegram_user_id=STRANGER)


async def test_only_the_account_that_opened_the_link_can_decide() -> None:
    world = World()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)

    with pytest.raises(AppLoginNotYoursError):
        await world.login.decide(request.id, telegram_user_id=STRANGER, approve=True)
    assert world.requests.items[request.id].status is AppLoginStatus.PENDING


async def test_an_unclaimed_request_cannot_be_decided() -> None:
    world = World()
    started = await world.start()

    with pytest.raises(AppLoginNotYoursError):
        await world.login.decide(started.request_id, telegram_user_id=OWNER, approve=True)


async def test_an_expired_request_cannot_be_claimed() -> None:
    world = World()
    started = await world.start()
    world.clock.advance(REQUEST_TTL)

    with pytest.raises(AppLoginExpiredError):
        await world.login.claim(started.code, telegram_user_id=OWNER)
    outcome = await world.login.poll(started.poll_token, context=CONTEXT)
    assert outcome.status is AppLoginStatus.EXPIRED


async def test_an_expired_request_cannot_be_approved() -> None:
    world = World()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)
    world.clock.advance(REQUEST_TTL + timedelta(seconds=1))

    with pytest.raises(AppLoginExpiredError):
        await world.login.decide(request.id, telegram_user_id=OWNER, approve=True)


async def test_an_approval_nobody_collected_in_time_expires() -> None:
    world = World()
    await world.customer()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)
    await world.login.decide(request.id, telegram_user_id=OWNER, approve=True)
    world.clock.advance(REQUEST_TTL)

    outcome = await world.login.poll(started.poll_token, context=CONTEXT)

    assert outcome.status is AppLoginStatus.EXPIRED
    assert outcome.result is None


async def test_unknown_codes_and_poll_tokens_are_not_found() -> None:
    world = World()
    await world.start()

    with pytest.raises(AppLoginNotFoundError):
        await world.login.claim("not-a-real-code", telegram_user_id=OWNER)
    with pytest.raises(AppLoginNotFoundError):
        await world.login.poll("not-a-real-poll-token", context=CONTEXT)


async def test_a_suspended_customer_gets_no_session() -> None:
    world = World()
    user = await world.customer()
    started = await world.start()
    request = await world.login.claim(started.code, telegram_user_id=OWNER)
    await world.login.decide(request.id, telegram_user_id=OWNER, approve=True)
    user.suspend(reason="abuse")

    with pytest.raises(AccountSuspendedError):
        await world.login.poll(started.poll_token, context=CONTEXT)


# -- devices -------------------------------------------------------------------


async def _signed_in(world: World, *, telegram_id: int, device_id: str) -> uuid.UUID:
    started = await world.start(device_id=device_id)
    request = await world.login.claim(started.code, telegram_user_id=telegram_id)
    await world.login.decide(request.id, telegram_user_id=telegram_id, approve=True)
    outcome = await world.login.poll(started.poll_token, context=CONTEXT)
    assert outcome.result is not None
    return outcome.result.tokens.session_id


async def test_the_device_list_shows_only_app_sessions() -> None:
    world = World()
    user = await world.customer()
    app_session = await _signed_in(world, telegram_id=OWNER, device_id="dev-1")
    # A Mini App login is a session too, but not a device the customer would recognise.
    await world.sessions.issue_pair(
        subject_type=SubjectType.USER,
        subject_id=user.id,
        method=AuthMethod.TELEGRAM_MINI_APP,
        context=CONTEXT,
    )

    devices = await world.login.devices(user.id)

    assert [d.session_id for d in devices] == [app_session]
    assert devices[0].name == "Pixel 6"


async def test_disconnecting_a_device_revokes_its_session() -> None:
    world = World()
    user = await world.customer()
    session_id = await _signed_in(world, telegram_id=OWNER, device_id="dev-1")

    assert await world.login.disconnect(user.id, session_id) is True

    session = await world.session_records.get(session_id)
    assert session is not None and session.is_revoked
    assert await world.login.devices(user.id) == []


async def test_nobody_can_disconnect_someone_elses_device() -> None:
    world = World()
    await world.customer(OWNER)
    stranger = await world.customer(STRANGER)
    session_id = await _signed_in(world, telegram_id=OWNER, device_id="dev-1")

    assert await world.login.disconnect(stranger.id, session_id) is False

    session = await world.session_records.get(session_id)
    assert session is not None and not session.is_revoked
