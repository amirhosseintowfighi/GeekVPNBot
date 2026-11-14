"""A role that cannot do something in the panel cannot do it from the bot.

The bot's operator area checked one thing: that the caller was staff. Every
role passed - so a VIEWER, read-only by definition, could approve a receipt,
credit a wallet, suspend a customer or extend their service from Telegram,
and SUPPORT could approve payments the panel keeps from them. The panel and
the bot answered the same question differently.

Every operator button and every step of an operator conversation now names
the permission the panel requires for the same act, and the admin router
refuses the call before the handler runs.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.domain.identity.permissions import AdminRole, Permission, permissions_for_role
from geekvpn.presentation.bot import admin_access
from geekvpn.presentation.bot.admin_access import (
    ACTION_PERMISSIONS,
    STATE_PERMISSIONS,
    AdminAccess,
    required_permission,
)
from geekvpn.presentation.bot.ui.callbacks import AdminCB

pytestmark = pytest.mark.unit

HANDLERS = pathlib.Path(__file__).resolve().parents[3] / "src/geekvpn/presentation/bot/handlers"


def _actions_used() -> set[str]:
    """Every `AdminCB(action=...)` any handler file builds or filters on."""
    found: set[str] = set()
    for path in HANDLERS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("AdminCB"):
                for kw in node.keywords:
                    if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                        found.add(str(kw.value.value))
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "AdminCB.filter":
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                        found.add(inner.value)
    return found


def test_every_operator_button_names_a_permission() -> None:
    """A button added without an entry would be refused, loudly, in testing."""
    missing = _actions_used() - set(ACTION_PERMISSIONS)
    assert not missing, f"no permission declared for: {sorted(missing)}"


def test_every_operator_conversation_step_names_a_permission() -> None:
    from geekvpn.presentation.bot.handlers.admin import AdminFlow
    from geekvpn.presentation.bot.handlers.admin_pin import PinFlow
    from geekvpn.presentation.bot.handlers.admin_texts import TextFlow

    states = {s.state for group in (AdminFlow, PinFlow, TextFlow) for s in group.__all_states__}
    assert states <= set(STATE_PERMISSIONS)


@pytest.mark.parametrize(
    ("role", "action", "allowed"),
    [
        (AdminRole.VIEWER, "approve", False),
        (AdminRole.VIEWER, "wallet_add", False),
        (AdminRole.VIEWER, "sub_extend", False),
        (AdminRole.VIEWER, "suspend", False),
        (AdminRole.VIEWER, "payments", True),
        (AdminRole.SUPPORT, "approve", False),
        (AdminRole.SUPPORT, "reply", True),
        (AdminRole.SUPPORT, "sub_extend", True),
        (AdminRole.FINANCE, "approve", True),
        (AdminRole.FINANCE, "sub_revoke", False),
        (AdminRole.ADMIN, "approve", True),
        (AdminRole.ADMIN, "sub_revoke", True),
    ],
)
def test_the_panels_role_matrix_decides(role: AdminRole, action: str, allowed: bool) -> None:
    permission = required_permission(action=action)
    assert permission is not None
    assert (permission in permissions_for_role(role)) is allowed


class _Admin:
    def __init__(self, role: AdminRole) -> None:
        self.id = uuid.uuid4()
        self.role = role
        self.status = SimpleNamespace(can_authenticate=True)

    def has_permission(self, permission: Permission) -> bool:
        return permission in permissions_for_role(self.role)


class _Query:
    def __init__(self) -> None:
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False, **_: Any) -> None:
        self.answers.append((text, show_alert))


async def _run(
    role: AdminRole, action: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[bool, _Query]:
    admin = _Admin(role)

    async def current(scope: Any, user: Any) -> Any:
        return admin

    monkeypatch.setattr(admin_access, "_current_staff", current)
    reached: list[bool] = []

    async def handler(event: Any, data: dict[str, Any]) -> None:
        reached.append(True)

    query = _Query()
    middleware = AdminAccess()
    await middleware(
        handler,
        query,  # type: ignore[arg-type]
        {"callback_data": AdminCB(action=action), "scope": object(), "user": object()},
    )
    return bool(reached), query


async def test_a_viewer_pressing_approve_never_reaches_the_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached, query = await _run(AdminRole.VIEWER, "approve", monkeypatch)

    assert not reached
    assert query.answers and query.answers[0][1] is True


async def test_finance_pressing_approve_reaches_the_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached, _ = await _run(AdminRole.FINANCE, "approve", monkeypatch)

    assert reached
