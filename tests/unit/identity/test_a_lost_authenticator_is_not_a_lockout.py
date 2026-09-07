"""Signing in with a recovery code when the TOTP device is gone.

`recovery_codes.py` was complete the day it was written - generation, scrypt
hashing, single use, constant-time comparison, the low-codes nudge - and
nothing called any of it. No column stored a code, no route spent one. So an
operator who lost their phone had exactly one way back into their own panel:
an UPDATE against production by whoever holds the database password, which is
both an outage and the least auditable privilege escalation in the system.

The same class of bug as the referral table and the join gate: finished code
that no entry point reaches.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.identity.authenticate_admin import AuthenticateAdmin
from geekvpn.application.identity.dto import RequestContext
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.errors import TwoFactorInvalidError, TwoFactorRequiredError
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.infrastructure.security.recovery_adapter import ScryptRecoveryCodes

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)
PASSWORD = "correct horse"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Passwords:
    def hash(self, password: str) -> str:
        return f"h:{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"h:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


class Totp:
    def generate_secret(self) -> str:
        return "S"

    def provisioning_uri(self, *, secret: str, account: str, issuer: str) -> str:
        return ""

    def verify(self, *, secret: str, code: str) -> bool:
        return code == "000000"


class Admins:
    def __init__(self, admin: Admin) -> None:
        self.admin = admin

    async def get_by_username(self, username: str) -> Admin | None:
        return self.admin if self.admin.username == username else None

    async def update(self, admin: Admin) -> None:
        self.admin = admin


class Sessions:
    async def issue_pair(self, **kwargs: object) -> object:
        return object()


class Audit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def record(self, action: object, **kwargs: object) -> None:
        self.actions.append(str(getattr(action, "value", action)))


class Limiter:
    async def hit(self, *args: object, **kwargs: object) -> object:
        return type("V", (), {"allowed": True, "retry_after_seconds": 0})()


def _admin(hashes: tuple[str, ...]) -> Admin:
    return Admin(
        uuid.uuid4(),
        username="amir",
        password_hash=f"h:{PASSWORD}",
        role=AdminRole.SUPER_ADMIN,
        totp_secret="SECRET",
        is_totp_enabled=True,
        recovery_code_hashes=hashes,
    )


def _service(admins: Admins, audit: Audit) -> AuthenticateAdmin:
    return AuthenticateAdmin(
        admins=admins,
        passwords=Passwords(),
        totp=Totp(),
        recovery=ScryptRecoveryCodes(),
        sessions=Sessions(),
        clock=FixedClock(),
        audit=audit,
        rate_limiter=Limiter(),
    )


def _sign_in(service: AuthenticateAdmin, **kwargs: object):
    return asyncio.run(
        service.execute(
            username="amir",
            password=PASSWORD,
            context=RequestContext(device_label="test"),
            **kwargs,
        )
    )


def _issued() -> tuple[tuple[str, ...], tuple[str, ...]]:
    return ScryptRecoveryCodes().issue(3)


def test_a_recovery_code_gets_somebody_in():
    codes, hashes = _issued()
    admins = Admins(_admin(hashes))

    _sign_in(_service(admins, Audit()), recovery_code=codes[0])

    # No exception is the assertion: the login completed without the phone.


def test_the_code_is_burnt_on_use():
    """A recovery code that works twice is a password, and a weak one."""
    codes, hashes = _issued()
    admins = Admins(_admin(hashes))
    service = _service(admins, Audit())

    _sign_in(service, recovery_code=codes[0])

    assert len(admins.admin.recovery_code_hashes) == len(hashes) - 1
    with pytest.raises(TwoFactorInvalidError):
        _sign_in(service, recovery_code=codes[0])


def test_the_other_codes_still_work():
    codes, hashes = _issued()
    admins = Admins(_admin(hashes))
    service = _service(admins, Audit())

    _sign_in(service, recovery_code=codes[0])
    _sign_in(service, recovery_code=codes[2])

    assert len(admins.admin.recovery_code_hashes) == len(hashes) - 2


def test_a_wrong_code_does_not_destroy_a_good_one():
    """A mistyped code must not spend a code the owner still needs."""
    _codes, hashes = _issued()
    admins = Admins(_admin(hashes))

    with pytest.raises(TwoFactorInvalidError):
        _sign_in(_service(admins, Audit()), recovery_code="ZZZZ-ZZZZ")

    assert len(admins.admin.recovery_code_hashes) == len(hashes)


def test_it_works_when_no_totp_secret_was_ever_enrolled():
    """The lockout this exists for. A super admin with 2FA required and no
    secret is refused a password-only login - correctly - and had no other
    door at all."""
    codes, hashes = _issued()
    admin = _admin(hashes)
    admin.totp_secret = None
    admins = Admins(admin)

    _sign_in(_service(admins, Audit()), recovery_code=codes[0])


def test_no_second_factor_at_all_is_still_refused():
    _codes, hashes = _issued()
    admins = Admins(_admin(hashes))

    with pytest.raises(TwoFactorRequiredError):
        _sign_in(_service(admins, Audit()))


def test_an_admin_with_no_codes_cannot_be_talked_into_one():
    admins = Admins(_admin(()))

    with pytest.raises(TwoFactorInvalidError):
        _sign_in(_service(admins, Audit()), recovery_code="ABCD-EFGH")


def test_using_one_is_its_own_audit_entry():
    """"Somebody got in without their authenticator" is exactly the line a
    person reviewing a breach is looking for, and it must not be buried in an
    ordinary successful login."""
    codes, hashes = _issued()
    audit = Audit()

    _sign_in(_service(Admins(_admin(hashes)), audit), recovery_code=codes[0])

    assert "auth.recovery_code.used" in audit.actions


def test_a_failed_attempt_is_audited_too():
    _codes, hashes = _issued()
    audit = Audit()

    with pytest.raises(TwoFactorInvalidError):
        _sign_in(_service(Admins(_admin(hashes)), audit), recovery_code="ZZZZ-ZZZZ")

    assert "auth.totp.failed" in audit.actions


def test_the_normal_totp_login_is_untouched():
    _codes, hashes = _issued()

    _sign_in(_service(Admins(_admin(hashes)), Audit()), totp_code="000000")


def test_a_corrupt_stored_hash_is_a_refusal_not_a_crash():
    """One unparseable row must not lock somebody out of every code they hold,
    and must not surface as a 500 on a login form."""
    admins = Admins(_admin(("not-a-hash",)))

    with pytest.raises(TwoFactorInvalidError):
        _sign_in(_service(admins, Audit()), recovery_code="ABCD-EFGH")
