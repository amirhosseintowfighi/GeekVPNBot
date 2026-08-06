"""User and Admin aggregate behaviour."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.identity.admin import LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS, Admin
from geekvpn.domain.identity.enums import AdminStatus, AuthMethod, Language, UserStatus
from geekvpn.domain.identity.errors import (
    AccountLockedError,
    AccountSuspendedError,
    MissingPermissionError,
)
from geekvpn.domain.identity.events import UserRegistered, UserSuspended
from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.domain.identity.user import User

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_user(**kwargs) -> User:
    defaults = {
        "user_id": uuid.uuid4(),
        "telegram_id": 1,
        "referral_code": "ABCD2345",
        "now": NOW,
    }
    defaults.update(kwargs)
    return User.register(**defaults)


def test_registering_records_an_event():
    events = make_user().collect_events()
    assert len(events) == 1
    assert isinstance(events[0], UserRegistered)
    assert events[0].name == "identity.user.registered.v1"


def test_events_are_collected_only_once():
    user = make_user()
    user.collect_events()
    assert user.collect_events() == []


def test_a_user_cannot_refer_themselves():
    assert make_user(referral_code="SELF1234", referred_by_code="SELF1234").referred_by_code is None


def test_display_name_falls_back_sensibly():
    assert make_user(first_name="Amir").display_name == "Amir"
    assert make_user(username="amir").display_name == "@amir"
    assert make_user(telegram_id=42).display_name == "user-42"


def test_refresh_profile_reports_whether_anything_changed():
    user = make_user(username="amir", first_name="Amir")
    unchanged = user.refresh_profile(
        username="amir", first_name="Amir", last_name=None, language=Language.FA
    )
    changed = user.refresh_profile(
        username="amir2", first_name="Amir", last_name=None, language=Language.FA
    )
    assert unchanged is False
    assert changed is True


def test_a_suspended_user_cannot_authenticate():
    user = make_user()
    user.suspend(reason="chargeback")

    assert user.status is UserStatus.SUSPENDED
    assert any(isinstance(e, UserSuspended) for e in user.collect_events())
    with pytest.raises(AccountSuspendedError):
        user.mark_authenticated(method=AuthMethod.TELEGRAM_BOT, now=NOW)


def test_reinstating_restores_access():
    user = make_user()
    user.suspend(reason="review")
    user.reinstate()
    user.mark_authenticated(method=AuthMethod.TELEGRAM_BOT, now=NOW)
    assert user.last_seen_at == NOW


def make_admin(role: AdminRole = AdminRole.SUPPORT, **kwargs) -> Admin:
    return Admin(uuid.uuid4(), username="a", password_hash="h", role=role, **kwargs)


def test_require_permission_raises_for_a_missing_permission():
    admin = make_admin()
    admin.require_permission(Permission.TICKETS_REPLY)
    with pytest.raises(MissingPermissionError):
        admin.require_permission(Permission.ADMINS_WRITE)


def test_a_denied_permission_is_removed_from_the_effective_set():
    admin = make_admin(
        AdminRole.SUPER_ADMIN, denied_permissions=frozenset({Permission.WALLET_ADJUST})
    )
    assert not admin.has_permission(Permission.WALLET_ADJUST)


def test_lockout_engages_after_the_threshold():
    admin = make_admin()
    for _ in range(MAX_FAILED_ATTEMPTS):
        admin.register_failed_attempt(now=NOW)

    assert admin.is_locked(now=NOW)
    assert admin.locked_until == NOW + LOCKOUT_DURATION
    with pytest.raises(AccountLockedError):
        admin.ensure_can_authenticate(now=NOW)


def test_lockout_lifts_once_the_window_passes():
    admin = make_admin()
    for _ in range(MAX_FAILED_ATTEMPTS):
        admin.register_failed_attempt(now=NOW)
    admin.ensure_can_authenticate(now=NOW + LOCKOUT_DURATION + timedelta(seconds=1))


def test_a_disabled_admin_cannot_authenticate():
    with pytest.raises(AccountSuspendedError):
        make_admin(status=AdminStatus.DISABLED).ensure_can_authenticate(now=NOW)


def test_super_admins_always_require_two_factor():
    assert make_admin(AdminRole.SUPER_ADMIN).requires_totp is True
    assert make_admin(AdminRole.SUPPORT).requires_totp is False
    assert make_admin(AdminRole.SUPPORT, is_totp_enabled=True).requires_totp is True
