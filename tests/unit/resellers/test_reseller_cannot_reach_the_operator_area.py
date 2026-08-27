"""A reseller taps the operator command and gets nothing.

The bot has no `requires(...)` in front of a handler - `_guard` is the entire
door. It used to ask two things: does an admin account exist for this Telegram
id, and can it authenticate. Both are true of every reseller, because that
account with its Telegram id is exactly how a reseller reaches their *own*
area. So a reseller tapping the operator command got the payment queue, the
customer search, and the platform's takings.

The API had the same hole one level up and was fixed the same day; this is the
other half, in the surface where a permission set is not consulted at all.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from geekvpn.domain.identity.enums import AdminStatus
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.presentation.bot.handlers import admin as bot_admin

pytestmark = pytest.mark.unit


class Account:
    """Just enough of `Admin` for the guard."""

    def __init__(self, role: AdminRole, status: AdminStatus = AdminStatus.ACTIVE) -> None:
        self.id = uuid.uuid4()
        self.role = role
        self.status = status
        self.telegram_id = 87791922


class Admins:
    def __init__(self, account: Account | None) -> None:
        self._account = account

    async def get_by_telegram_id(self, telegram_id: int) -> Any:
        return self._account


class Scope:
    def __init__(self, account: Account | None) -> None:
        self.admins = Admins(account)


class User:
    def __init__(self, telegram_id: int = 87791922) -> None:
        self.telegram_id = telegram_id


async def test_a_reseller_is_refused_the_operator_area():
    """The whole point. They hold an admin account and it authenticates."""
    scope = Scope(Account(AdminRole.RESELLER))

    assert await bot_admin._guard(scope, User()) is None


async def test_the_operator_entry_is_not_even_offered_to_them():
    """Showing a button that always refuses is worse than showing none: it
    tells a reseller there is a door and invites them to keep trying it."""
    scope = Scope(Account(AdminRole.RESELLER))

    assert await bot_admin.is_admin(scope, User()) is False


@pytest.mark.parametrize(
    "role",
    [AdminRole.SUPER_ADMIN, AdminRole.ADMIN, AdminRole.FINANCE, AdminRole.SUPPORT],
)
async def test_real_operators_still_get_in(role: AdminRole):
    """The guard has to keep letting staff through - a fix that closed the door
    on everybody would look identical from the reseller's side."""
    scope = Scope(Account(role))

    assert await bot_admin._guard(scope, User()) is not None


async def test_a_disabled_operator_is_still_refused():
    """The rule that was already there, kept."""
    scope = Scope(Account(AdminRole.ADMIN, AdminStatus.DISABLED))

    assert await bot_admin._guard(scope, User()) is None


async def test_somebody_with_no_admin_account_is_refused():
    assert await bot_admin._guard(Scope(None), User()) is None
