"""Admin login: lockout, 2FA, enumeration resistance, IP allow-listing."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest

from geekvpn.application.identity.authenticate_admin import AuthenticateAdmin
from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.identity.session_service import SessionPolicy, SessionService
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.admin import MAX_FAILED_ATTEMPTS, Admin
from geekvpn.domain.identity.errors import (
    AccountLockedError,
    InvalidCredentialsError,
    IpNotAllowedError,
    TwoFactorInvalidError,
    TwoFactorRequiredError,
)
from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.infrastructure.security.ip_allowlist import IpAllowlist
from geekvpn.infrastructure.security.jwt import JwtAccessTokenService
from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory
from geekvpn.infrastructure.security.totp import Rfc6238TotpService
from tests.fakes import (
    AllowingRateLimiter,
    FrozenClock,
    InMemoryAdminRepository,
    InMemoryRevocationList,
    InMemorySessionRepository,
    RecordingAudit,
)

CONTEXT = RequestContext(ip="10.0.0.1", user_agent="admin-panel")
PASSWORD = "correct-horse-battery-staple"


class FakeHasher:
    """Argon2 with production parameters costs ~100ms and this file performs
    dozens of logins. Argon2 itself is covered in test_password_hasher."""

    def __init__(self) -> None:
        self.rehash_requested = False

    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return self.rehash_requested


def build(*, admin: Admin | None = None, allowed_ips=(), limiter=None):
    clock = FrozenClock()
    admins = InMemoryAdminRepository()
    if admin is not None:
        admins.items[admin.id] = admin
    audit = RecordingAudit()
    sessions = SessionService(
        sessions=InMemorySessionRepository(),
        access_tokens=JwtAccessTokenService(
            secret_key="z" * 48,
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
    hasher = FakeHasher()
    use_case = AuthenticateAdmin(
        admins=admins,
        passwords=hasher,
        totp=Rfc6238TotpService(),
        sessions=sessions,
        clock=clock,
        audit=audit,
        rate_limiter=limiter or AllowingRateLimiter(),
        allowlist=IpAllowlist.from_entries(allowed_ips),
    )
    return use_case, admins, audit, clock, hasher


def make_admin(role: AdminRole = AdminRole.SUPPORT, **kwargs) -> Admin:
    return Admin(
        uuid.uuid4(),
        username="amir",
        password_hash=f"hashed::{PASSWORD}",
        role=role,
        **kwargs,
    )


async def test_a_valid_login_returns_tokens_and_the_permission_set():
    use_case, _, audit, _, _ = build(admin=make_admin())

    result = await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)

    assert result.admin is not None
    assert result.admin.role == AdminRole.SUPPORT.value
    assert Permission.TICKETS_REPLY.value in result.admin.permissions
    assert Permission.WALLET_ADJUST.value not in result.admin.permissions
    assert result.tokens.access_token
    assert AuditAction.AUTH_LOGIN_SUCCEEDED in audit.actions()


async def test_an_unknown_username_looks_exactly_like_a_wrong_password():
    use_case, _, audit, _, _ = build()
    with pytest.raises(InvalidCredentialsError) as unknown:
        await use_case.execute(username="nobody", password=PASSWORD, context=CONTEXT)

    use_case2, _, _, _, _ = build(admin=make_admin())
    with pytest.raises(InvalidCredentialsError) as wrong:
        await use_case2.execute(username="amir", password="wrong", context=CONTEXT)

    assert unknown.value.message == wrong.value.message
    assert unknown.value.code == wrong.value.code
    assert AuditAction.AUTH_LOGIN_FAILED in audit.actions()


async def test_repeated_failures_lock_the_account():
    use_case, _, audit, _, _ = build(admin=make_admin())
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(username="amir", password="wrong", context=CONTEXT)

    # Even the correct password is refused now.
    with pytest.raises(AccountLockedError):
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)
    assert AuditAction.AUTH_ACCOUNT_LOCKED in audit.actions()


async def test_the_lock_expires():
    use_case, _, _, clock, _ = build(admin=make_admin())
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(username="amir", password="wrong", context=CONTEXT)

    clock.advance(timedelta(minutes=16))
    assert (
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)
    ).admin is not None


async def test_a_successful_login_clears_the_failure_counter():
    admin = make_admin()
    use_case, admins, _, _, _ = build(admin=admin)
    with pytest.raises(InvalidCredentialsError):
        await use_case.execute(username="amir", password="wrong", context=CONTEXT)

    await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)
    assert admins.items[admin.id].failed_attempts == 0


async def test_a_super_admin_must_present_a_second_factor():
    secret = Rfc6238TotpService().generate_secret()
    use_case, _, _, _, _ = build(
        admin=make_admin(AdminRole.SUPER_ADMIN, totp_secret=secret, is_totp_enabled=True)
    )
    with pytest.raises(TwoFactorRequiredError):
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)


async def test_a_wrong_second_factor_is_refused_and_audited():
    secret = Rfc6238TotpService().generate_secret()
    use_case, _, audit, _, _ = build(
        admin=make_admin(AdminRole.SUPER_ADMIN, totp_secret=secret, is_totp_enabled=True)
    )
    with pytest.raises(TwoFactorInvalidError):
        await use_case.execute(
            username="amir", password=PASSWORD, totp_code="000000", context=CONTEXT
        )
    assert AuditAction.AUTH_TOTP_FAILED in audit.actions()
    assert any(entry["outcome"] is AuditOutcome.FAILURE for entry in audit.entries)


async def test_a_correct_second_factor_is_accepted():
    totp = Rfc6238TotpService()
    secret = totp.generate_secret()
    use_case, _, _, _, _ = build(
        admin=make_admin(AdminRole.SUPER_ADMIN, totp_secret=secret, is_totp_enabled=True)
    )

    code = totp.code_at(secret=secret, timestamp=time.time())
    result = await use_case.execute(
        username="amir", password=PASSWORD, totp_code=code, context=CONTEXT
    )
    assert result.admin is not None


async def test_a_super_admin_without_an_enrolled_secret_cannot_log_in():
    """Mandatory 2FA must never silently degrade to password-only."""
    use_case, _, _, _, _ = build(admin=make_admin(AdminRole.SUPER_ADMIN))
    with pytest.raises(TwoFactorRequiredError):
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)


async def test_an_ip_outside_the_allowlist_is_refused():
    use_case, _, _, _, _ = build(admin=make_admin(), allowed_ips=("203.0.113.9",))
    with pytest.raises(IpNotAllowedError):
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)


async def test_an_ip_on_the_allowlist_is_accepted():
    use_case, _, _, _, _ = build(admin=make_admin(), allowed_ips=("10.0.0.1",))
    assert (
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)
    ).admin is not None


async def test_a_cidr_range_admits_every_address_inside_it():
    """The allowlist was a `frozenset[str]` compared with `in`, so the CIDR an
    operator is told to write in .env.example matched literally nothing and
    locked the whole team out of the admin panel."""
    use_case, _, _, _, _ = build(admin=make_admin(), allowed_ips=("10.0.0.0/24",))

    assert (
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)
    ).admin is not None


async def test_an_unknown_address_is_refused_when_an_allowlist_is_configured():
    """`client_ip` returns None when it cannot establish who called. That must
    not read as "allowed" - it is the state a spoofed header now produces."""
    use_case, _, _, _, _ = build(admin=make_admin(), allowed_ips=("10.0.0.0/24",))

    with pytest.raises(IpNotAllowedError):
        await use_case.execute(
            username="amir",
            password=PASSWORD,
            context=RequestContext(ip=None, user_agent="admin-panel"),
        )


async def test_the_rate_limiter_blocks_before_the_password_is_checked():
    use_case, _, _, _, _ = build(admin=make_admin(), limiter=AllowingRateLimiter(allowed=False))
    with pytest.raises(AccountLockedError):
        await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)


async def test_both_the_username_and_the_ip_are_rate_limited():
    limiter = AllowingRateLimiter()
    use_case, _, _, _, _ = build(admin=make_admin(), limiter=limiter)

    await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)

    assert any("user" in key for key in limiter.hits)
    assert any("ip" in key for key in limiter.hits)


async def test_an_outdated_hash_is_upgraded_on_a_successful_login():
    admin = make_admin()
    use_case, admins, _, _, hasher = build(admin=admin)
    hasher.rehash_requested = True

    await use_case.execute(username="amir", password=PASSWORD, context=CONTEXT)

    assert admins.items[admin.id].password_changed_at is not None
