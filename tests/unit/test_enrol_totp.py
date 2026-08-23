"""A super admin needs a second factor, so something has to issue one.

`Admin.requires_totp` is true for a super admin whether or not a secret was
ever enrolled, and `Admin.enable_totp` had no caller anywhere in the project -
nor did `TotpService.generate_secret`, which the port declared for an enrolment
flow nobody wrote. The account the installer creates therefore demanded a code
that could not exist, and the panel was locked from the moment it was built.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest

from geekvpn.application.identity.authenticate_admin import AuthenticateAdmin
from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.identity.manage_admins import ManageAdmins
from geekvpn.application.identity.session_service import SessionPolicy, SessionService
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.errors import TwoFactorRequiredError
from geekvpn.domain.identity.permissions import AdminRole
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

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

PASSWORD = "correct-horse-battery-staple"
ISSUER = "Geek VPN"


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


def build(admin: Admin | None = None):
    clock = FrozenClock()
    admins = InMemoryAdminRepository()
    if admin is not None:
        admins.items[admin.id] = admin
    audit = RecordingAudit()
    totp = Rfc6238TotpService()

    manage = ManageAdmins(
        admins=admins,
        sessions=InMemorySessionRepository(),
        passwords=FakeHasher(),
        totp=totp,
        totp_issuer=ISSUER,
        clock=clock,
        audit=audit,
    )
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
    authenticate = AuthenticateAdmin(
        admins=admins,
        passwords=FakeHasher(),
        totp=totp,
        sessions=sessions,
        clock=clock,
        audit=audit,
        rate_limiter=AllowingRateLimiter(),
        allowlist=IpAllowlist.from_entries(()),
    )
    return manage, authenticate, admins, audit, totp, clock


def make_super_admin() -> Admin:
    return Admin(
        uuid.uuid4(),
        username="amir",
        password_hash=f"hashed::{PASSWORD}",
        role=AdminRole.SUPER_ADMIN,
    )


async def test_a_super_admin_without_an_enrolled_secret_cannot_sign_in() -> None:
    """The state every installation started in."""
    _, authenticate, _, _, _, _ = build(make_super_admin())

    with pytest.raises(TwoFactorRequiredError) as refused:
        await authenticate.execute(
            username="amir", password=PASSWORD, context=RequestContext(ip="10.0.0.1")
        )

    assert refused.value.details.get("enrolment_required") is True


async def test_enrolment_lets_that_same_admin_sign_in_with_a_code() -> None:
    manage, authenticate, _, _, totp, _ = build(make_super_admin())

    enrolment = await manage.enrol_totp(username="amir")
    # Wall clock, not the frozen one: verification reads the real time,
    # because a TOTP step is a fact about the world and not about this test.
    code = totp.code_at(secret=enrolment.secret, timestamp=time.time())

    result = await authenticate.execute(
        username="amir",
        password=PASSWORD,
        totp_code=code,
        context=RequestContext(ip="10.0.0.1"),
    )

    assert result.admin is not None
    assert result.admin.is_totp_enabled is True


async def test_the_secret_is_handed_back_in_a_form_an_authenticator_accepts() -> None:
    manage, _, _, _, _, _ = build(make_super_admin())

    enrolment = await manage.enrol_totp(username="amir")

    assert enrolment.username == "amir"
    assert enrolment.provisioning_uri.startswith("otpauth://totp/")
    assert f"secret={enrolment.secret}" in enrolment.provisioning_uri


async def test_re_enrolment_replaces_the_secret_so_a_lost_phone_is_recoverable() -> None:
    manage, _, _, _, _, _ = build(make_super_admin())

    first = await manage.enrol_totp(username="amir")
    second = await manage.enrol_totp(username="amir")

    assert first.secret != second.secret


async def test_enrolment_is_audited() -> None:
    manage, _, _, audit, _, _ = build(make_super_admin())

    await manage.enrol_totp(username="amir")

    assert AuditAction.AUTH_TOTP_ENABLED in audit.actions()


async def test_enrolling_an_unknown_administrator_is_refused() -> None:
    manage, _, _, _, _, _ = build()

    with pytest.raises(NotFoundError):
        await manage.enrol_totp(username="nobody")
