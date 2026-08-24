"""An administrator with no Telegram id can sign in and do nothing.

`admin_actor_id` refuses every endpoint that records who acted unless the
administrator has a Telegram account attached - approving a payment, refunding
one, adjusting a wallet, answering a ticket, sending a broadcast. `create_admin`
never set one and nothing could set it afterwards, so the account the installer
creates was locked out of the entire money and support surface. The panel showed
"اطلاعات واردشده درست نیست", which sent the operator to re-read a form that was
never the problem.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.identity.manage_admins import ManageAdmins
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.infrastructure.security.totp import Rfc6238TotpService
from tests.fakes import (
    FrozenClock,
    InMemoryAdminRepository,
    InMemorySessionRepository,
    RecordingAudit,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


def build(admin: Admin | None = None):
    admins = InMemoryAdminRepository()
    if admin is not None:
        admins.items[admin.id] = admin
    audit = RecordingAudit()
    manage = ManageAdmins(
        admins=admins,
        sessions=InMemorySessionRepository(),
        passwords=FakeHasher(),
        totp=Rfc6238TotpService(),
        totp_issuer="Geek VPN",
        clock=FrozenClock(),
        audit=audit,
    )
    return manage, admins, audit


def make_admin(telegram_id: int | None = None) -> Admin:
    return Admin(
        uuid.uuid4(),
        username="amir",
        password_hash="hashed::x",
        role=AdminRole.SUPER_ADMIN,
        telegram_id=telegram_id,
    )


async def test_the_installer_created_administrator_has_no_telegram_id() -> None:
    """The state every installation started in, and the reason for this file."""
    admin = make_admin()

    assert admin.telegram_id is None


async def test_linking_attaches_the_account_the_administrator_acts_through() -> None:
    admin = make_admin()
    manage, admins, _ = build(admin)

    profile = await manage.link_telegram(username="amir", telegram_id=123456789)

    assert profile.username == "amir"
    assert admins.items[admin.id].telegram_id == 123456789


async def test_relinking_replaces_the_previous_account() -> None:
    """An operator changing Telegram accounts must not need a new admin."""
    admin = make_admin(telegram_id=111)
    manage, admins, _ = build(admin)

    await manage.link_telegram(username="amir", telegram_id=222)

    assert admins.items[admin.id].telegram_id == 222


async def test_linking_is_audited_with_both_sides_of_the_change() -> None:
    admin = make_admin(telegram_id=111)
    manage, _, audit = build(admin)

    await manage.link_telegram(username="amir", telegram_id=222)

    assert AuditAction.ADMIN_UPDATED in audit.actions()
    entry = next(e for e in audit.entries if e["action"] is AuditAction.ADMIN_UPDATED)
    assert entry["metadata"]["previous_telegram_id"] == 111
    assert entry["metadata"]["new_telegram_id"] == 222


async def test_linking_an_unknown_administrator_is_refused() -> None:
    manage, _, _ = build()

    with pytest.raises(NotFoundError):
        await manage.link_telegram(username="nobody", telegram_id=1)
