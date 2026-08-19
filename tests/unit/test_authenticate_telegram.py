"""Customer authentication use case."""

from __future__ import annotations

from datetime import timedelta

import pytest

from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.identity.session_service import SessionPolicy, SessionService
from geekvpn.application.ports.telegram_auth import TelegramIdentity
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.identity.enums import AuthMethod, Language
from geekvpn.domain.identity.errors import AccountSuspendedError
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService
from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory
from tests.fakes import (
    FrozenClock,
    InMemoryRevocationList,
    InMemorySessionRepository,
    InMemoryUserRepository,
    RecordingAudit,
)

CONTEXT = RequestContext(ip="5.6.7.8", user_agent="MiniApp")


class StubVerifier:
    def __init__(self, identity: TelegramIdentity) -> None:
        self.identity = identity
        #: What the last caller asked the freshness window to be.
        self.max_age_seconds: int | None = None

    def verify_mini_app(
        self, init_data: str, *, max_age_seconds: int | None = None
    ) -> TelegramIdentity:
        self.max_age_seconds = max_age_seconds
        return self.identity

    def verify_login_widget(self, payload: dict[str, str]) -> TelegramIdentity:
        return self.identity


def build(identity: TelegramIdentity, *, request_max_age_seconds: int = 900):
    clock = FrozenClock()
    users = InMemoryUserRepository()
    audit = RecordingAudit()
    verifier = StubVerifier(identity)
    session_repository = InMemorySessionRepository()
    sessions = SessionService(
        sessions=session_repository,
        access_tokens=JwtAccessTokenService(
            secret_key="s" * 48,
            issuer="geekvpn",
            audience="geekvpn-clients",
            ttl=timedelta(minutes=15),
        ),
        refresh_tokens=Sha256RefreshTokenFactory(),
        clock=clock,
        audit=audit,
        revocations=InMemoryRevocationList(),
        user_policy=SessionPolicy(refresh_ttl=timedelta(days=30), absolute_ttl=timedelta(days=180)),
        admin_policy=SessionPolicy(
            refresh_ttl=timedelta(hours=12), absolute_ttl=timedelta(hours=24)
        ),
        access_ttl_seconds=900,
    )
    use_case = AuthenticateTelegramUser(
        users=users,
        verifier=verifier,
        sessions=sessions,
        clock=clock,
        audit=audit,
        request_max_age_seconds=request_max_age_seconds,
    )
    return use_case, users, audit, verifier, session_repository


IDENTITY = TelegramIdentity(
    telegram_id=555,
    method=AuthMethod.TELEGRAM_MINI_APP,
    username="amir",
    first_name="Amir",
    language_code="fa",
)


async def test_first_login_registers_the_customer():
    use_case, users, audit, _, _ = build(IDENTITY)

    result = await use_case.from_mini_app("init", context=CONTEXT)

    assert result.is_new_user is True
    assert result.user is not None
    assert result.user.telegram_id == 555
    assert result.user.language is Language.FA
    assert len(result.user.referral_code) == 8
    assert AuditAction.USER_REGISTERED in audit.actions()
    assert len(users.items) == 1


async def test_second_login_reuses_the_same_account():
    use_case, users, _, _, _ = build(IDENTITY)

    first = await use_case.from_mini_app("init", context=CONTEXT)
    second = await use_case.from_mini_app("init", context=CONTEXT)

    assert second.is_new_user is False
    assert first.user is not None and second.user is not None
    assert first.user.id == second.user.id
    assert len(users.items) == 1


async def test_a_renamed_telegram_profile_is_synced():
    use_case, _, _, verifier, _ = build(IDENTITY)
    await use_case.from_mini_app("init", context=CONTEXT)

    verifier.identity = TelegramIdentity(
        telegram_id=555,
        method=AuthMethod.TELEGRAM_MINI_APP,
        username="amir_new",
        first_name="Amir",
        language_code="en",
    )
    result = await use_case.from_mini_app("init", context=CONTEXT)

    assert result.user is not None
    assert result.user.username == "amir_new"
    assert result.user.language is Language.EN


async def test_a_referral_deep_link_is_recorded():
    identity = TelegramIdentity(
        telegram_id=777,
        method=AuthMethod.TELEGRAM_MINI_APP,
        start_param="ref_ABCD2345",
    )
    use_case, users, _, _, _ = build(identity)

    result = await use_case.from_mini_app("init", context=CONTEXT)

    assert result.user is not None
    assert users.items[result.user.id].referred_by_code == "ABCD2345"


async def test_a_suspended_customer_cannot_sign_in():
    use_case, users, _, _, _ = build(IDENTITY)
    result = await use_case.from_mini_app("init", context=CONTEXT)
    assert result.user is not None
    users.items[result.user.id].suspend(reason="fraud")

    with pytest.raises(AccountSuspendedError):
        await use_case.from_mini_app("init", context=CONTEXT)


async def test_referral_codes_avoid_ambiguous_characters():
    use_case, _, _, _, _ = build(IDENTITY)
    result = await use_case.from_mini_app("init", context=CONTEXT)
    assert result.user is not None
    assert not set(result.user.referral_code) & set("OIL01")


async def test_a_mini_app_request_is_verified_without_minting_a_session():
    """The Mini App re-sends initData on every call. Running the login use case
    there created a session row and a refresh token per request - and wrote an
    AUTH_LOGIN_SUCCEEDED entry per request, which buried every real sign-in."""
    use_case, _, audit, _, session_repository = build(IDENTITY)

    profile = await use_case.verify_mini_app_request("init")

    assert profile.telegram_id == 555
    assert session_repository.sessions == {}
    assert AuditAction.AUTH_LOGIN_SUCCEEDED not in audit.actions()


async def test_the_real_login_endpoint_still_mints_one():
    use_case, _, audit, _, session_repository = build(IDENTITY)

    result = await use_case.from_mini_app("init", context=CONTEXT)

    assert result.tokens.refresh_token
    assert len(session_repository.sessions) == 1
    assert AuditAction.AUTH_LOGIN_SUCCEEDED in audit.actions()


async def test_a_per_request_credential_gets_a_much_shorter_freshness_window():
    """A header replayed on every call gives an attacker many chances to capture
    it, and Telegram never refreshes `auth_date` while a Mini App stays open."""
    use_case, _, _, verifier, _ = build(IDENTITY, request_max_age_seconds=600)

    await use_case.verify_mini_app_request("init")
    assert verifier.max_age_seconds == 600

    await use_case.from_mini_app("init", context=CONTEXT)
    assert verifier.max_age_seconds is None  # the configured login window


async def test_a_suspended_customer_cannot_ride_a_still_valid_init_data():
    use_case, users, _, _, _ = build(IDENTITY)
    await use_case.verify_mini_app_request("init")
    user = next(iter(users.items.values()))
    user.suspend(reason="fraud")

    with pytest.raises(AccountSuspendedError):
        await use_case.verify_mini_app_request("init")
