"""A reseller's token must not open a single operator endpoint.

A reseller is not staff. They sign in through the same door and get the same
kind of token, and what stops that token from reading the whole platform is the
permission set behind it - nothing else.

It did not stop it. The role was written with the operator vocabulary -
`users.read`, `wallet.read`, `orders.read`, `subscriptions.write` - because
those are the words that described what a reseller does. Every one of them is
what an admin endpoint checks, so a reseller's token could list every customer
on the platform, read every wallet, and suspend anybody's subscription.

The scoping in `/api/v1/reseller` was never the problem. Those endpoints resolve
the caller to their own record and cannot be pointed elsewhere. The permissions
were keys to a different building, and the reseller router was simply not the
only door they fit.

This holds both halves: nothing an admin endpoint requires is in the reseller
role, and nothing the reseller router requires is outside it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from geekvpn.domain.identity.permissions import (
    RESELLER_PERMISSIONS,
    AdminRole,
    permissions_for_role,
)

pytestmark = pytest.mark.integration

ROUTERS = pathlib.Path(__file__).resolve().parents[2] / "src/geekvpn/presentation/api/routers"


def _required_permissions(path: pathlib.Path) -> set[str]:
    """Every `Permission.X` named inside a `requires(...)` call in one file."""
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        if name != "requires":
            continue
        for argument in node.args:
            if (
                isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "Permission"
            ):
                found.add(argument.attr)
    return found


def _admin_routers() -> list[pathlib.Path]:
    return [
        path
        for path in sorted(ROUTERS.glob("*.py"))
        # The reseller's own router is the one place these permissions belong.
        if path.name not in {"reseller.py", "__init__.py"}
    ]


def test_no_admin_endpoint_accepts_a_reseller_permission():
    """The dangerous direction. A reseller permission that an operator endpoint
    also checks is a reseller reading the whole platform."""
    reseller = {permission.name for permission in RESELLER_PERMISSIONS}
    leaks = {
        path.name: sorted(_required_permissions(path) & reseller)
        for path in _admin_routers()
        if _required_permissions(path) & reseller
    }

    assert not leaks, f"these operator endpoints accept a reseller's token: {leaks}"


def test_the_reseller_router_asks_for_nothing_else():
    """The other direction, and the one that actually broke. A permission
    borrowed from the operator vocabulary works perfectly here and also unlocks
    the admin endpoint that checks the same word."""
    reseller = {permission.name for permission in RESELLER_PERMISSIONS}
    asked = _required_permissions(ROUTERS / "reseller.py")

    assert asked, "the reseller router guards nothing"
    assert asked <= reseller, f"borrowed from the operator vocabulary: {sorted(asked - reseller)}"


def test_the_role_holds_exactly_those_and_no_more():
    assert permissions_for_role(AdminRole.RESELLER) == RESELLER_PERMISSIONS


def test_no_staff_role_picks_a_reseller_permission_up_by_accident():
    """VIEWER is derived from the `.read` suffix. A reseller permission spelled
    `reseller.read` would land in a staff role by the accident of a naming
    convention, which is how this kind of thing gets in."""
    for role in AdminRole:
        if role is AdminRole.RESELLER:
            continue
        # Including SUPER_ADMIN. These are not a bigger version of an
        # operator's job, they are a different job - and an operator holding
        # `reseller.portal` would reach an endpoint that then has to refuse
        # them for a second reason.
        assert not (permissions_for_role(role) & RESELLER_PERMISSIONS), role
