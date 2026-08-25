"""The bot's operator area, and who is allowed into it.

Access is the admin record's own `telegram_id`, so there is no second list of
"bot admins" to fall out of step with the real one. That makes the gate the
only thing standing between a customer and the approve button, which is why it
is tested from both sides rather than only the happy one.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.enums import AdminStatus
from geekvpn.domain.identity.permissions import AdminRole
from geekvpn.presentation.bot.handlers import admin as bot_admin

pytestmark = pytest.mark.unit


class Admins:
    def __init__(self, record: Admin | None) -> None:
        self._record = record

    async def get_by_telegram_id(self, telegram_id: int) -> Admin | None:
        if self._record is None or self._record.telegram_id != telegram_id:
            return None
        return self._record


class Scope:
    def __init__(self, record: Admin | None) -> None:
        self.admins = Admins(record)


class User:
    def __init__(self, telegram_id: int) -> None:
        self.telegram_id = telegram_id


def make_admin(
    *, telegram_id: int | None = 87791922, status: AdminStatus = AdminStatus.ACTIVE
) -> Admin:
    return Admin(
        uuid.uuid4(),
        username="owner",
        password_hash="x",
        role=AdminRole.SUPER_ADMIN,
        telegram_id=telegram_id,
        status=status,
    )


async def test_a_linked_admin_is_recognised() -> None:
    record = make_admin()
    got = await bot_admin.current_admin(Scope(record), User(87791922))

    assert got is record


async def test_a_customer_is_not() -> None:
    got = await bot_admin.current_admin(Scope(make_admin()), User(555))

    assert got is None


async def test_an_admin_who_never_linked_telegram_is_not() -> None:
    """Otherwise the account is reachable by whoever guesses the id."""
    got = await bot_admin.current_admin(Scope(make_admin(telegram_id=None)), User(87791922))

    assert got is None


@pytest.mark.parametrize(
    "status", [status for status in AdminStatus if not status.can_authenticate]
)
async def test_an_admin_who_cannot_sign_in_cannot_use_the_bot(status: AdminStatus) -> None:
    """Suspending someone must take the bot away at the same moment."""
    scope = Scope(make_admin(status=status))

    assert await bot_admin._guard(scope, User(87791922)) is None


async def test_the_bot_cannot_hand_out_the_role_that_hands_out_roles() -> None:
    """A super admin created from a chat is an audit trail nobody reads."""
    assert AdminRole.SUPER_ADMIN not in bot_admin.OFFERABLE_ROLES
    assert set(bot_admin.OFFERABLE_ROLES) == set(AdminRole) - {AdminRole.SUPER_ADMIN}


async def test_every_offerable_role_has_a_persian_label() -> None:
    """A missing label renders a button with an English enum value on it."""
    for role in AdminRole:
        assert role in bot_admin.ROLE_LABEL_FA


# -- every button must lead somewhere ---------------------------------------
#
# The reply keyboard shipped with eight of nine buttons answering "I did not
# understand that", because the caption and the handler were written in two
# places and drifted. Inline buttons carry a callback action instead of a
# caption, and drift the same way and just as silently.


def _actions() -> tuple[set[str], set[str]]:
    """(emitted by a button, handled by a callback handler)."""
    import ast
    from pathlib import Path

    source = Path(bot_admin.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    emitted: set[str] = set()
    handled: set[str] = set()

    for node in ast.walk(tree):
        # AdminCB(action="payments", ...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "AdminCB"
        ):
            for keyword in node.keywords:
                if keyword.arg == "action" and isinstance(keyword.value, ast.Constant):
                    emitted.add(str(keyword.value.value))
        # AdminCB.filter(F.action == "payments")
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Attribute)
            and node.left.attr == "action"
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
        ):
            handled.add(str(node.comparators[0].value))
        # AdminCB.filter(F.action.in_({"a", "b"})) - one handler, several
        # actions. Reading only `==` made these look unhandled, which is the
        # test being wrong about the code rather than the other way round.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "in_"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "action"
        ):
            for argument in node.args:
                if isinstance(argument, ast.Set | ast.List | ast.Tuple):
                    handled.update(
                        str(element.value)
                        for element in argument.elts
                        if isinstance(element, ast.Constant)
                    )

    return emitted, handled


def test_the_actions_were_found() -> None:
    emitted, handled = _actions()

    assert len(emitted) >= 8
    assert len(handled) >= 8


def test_every_button_action_has_a_handler() -> None:
    emitted, handled = _actions()

    # `_back(to)` builds a button from a variable, so the two navigation
    # targets it is called with are covered by their own handlers above.
    assert not emitted - handled, f"buttons that lead nowhere: {sorted(emitted - handled)}"


def test_no_handler_waits_on_an_action_nothing_sends() -> None:
    emitted, handled = _actions()

    assert not handled - emitted, f"handled but unreachable: {sorted(handled - emitted)}"
