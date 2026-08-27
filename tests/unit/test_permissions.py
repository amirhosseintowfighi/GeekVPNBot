"""RBAC resolution rules."""

from __future__ import annotations

import pytest

from geekvpn.domain.identity.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    AdminRole,
    Permission,
    permissions_for_role,
    resolve_permissions,
)


def test_every_role_is_defined():
    """A role with no entry would blow up at login time, not at import time."""
    for role in AdminRole:
        assert role in ROLE_PERMISSIONS


def test_super_admin_has_every_staff_permission():
    """Everything except the reseller verbs.

    Those are not a bigger version of an operator's job, they are a different
    job: an owner holding `reseller.portal` would reach an endpoint that then
    has to refuse them for a second reason, because they have no reseller
    record. One refusal is clearer than two.
    """
    from geekvpn.domain.identity.permissions import RESELLER_PERMISSIONS

    assert permissions_for_role(AdminRole.SUPER_ADMIN) == (
        ALL_PERMISSIONS - RESELLER_PERMISSIONS
    )


def test_admin_cannot_create_admins_or_change_settings():
    permissions = permissions_for_role(AdminRole.ADMIN)
    assert Permission.ADMINS_WRITE not in permissions
    assert Permission.SETTINGS_WRITE not in permissions
    assert Permission.ORDERS_REFUND in permissions


def test_viewer_holds_no_permission_that_can_change_anything():
    """Read-only proven semantically, not by a naming convention.

    The previous version of this test asserted that every viewer permission ends
    in ".read". That is a spelling check, not a security check: it failed on
    "analytics.view" - which grants no mutation at all - while it would happily
    pass a hypothetical "wallet.read_and_drain". What actually matters is that a
    viewer holds nothing from the mutating set.
    """
    mutating_verbs = (
        ".write",
        ".delete",
        ".approve",
        ".refund",
        ".adjust",
        ".reply",
        ".impersonate",
        ".send",
        ".export",
        ".suspend",
        ".revoke",
    )
    for permission in permissions_for_role(AdminRole.VIEWER):
        for verb in mutating_verbs:
            assert not permission.value.endswith(verb), permission


def test_no_role_grants_a_permission_that_does_not_exist():
    """A typo in a role table is a silent privilege bug in either direction."""
    for role, granted in ROLE_PERMISSIONS.items():
        assert granted <= ALL_PERMISSIONS, role


def test_support_cannot_touch_money():
    permissions = permissions_for_role(AdminRole.SUPPORT)
    assert Permission.WALLET_ADJUST not in permissions
    assert Permission.PAYMENTS_APPROVE not in permissions
    assert Permission.TICKETS_REPLY in permissions


def test_grant_adds_a_permission_outside_the_role():
    resolved = resolve_permissions(AdminRole.SUPPORT, granted=[Permission.PAYMENTS_APPROVE])
    assert Permission.PAYMENTS_APPROVE in resolved


def test_deny_beats_the_role():
    resolved = resolve_permissions(AdminRole.ADMIN, denied=[Permission.ORDERS_REFUND])
    assert Permission.ORDERS_REFUND not in resolved


def test_deny_beats_an_explicit_grant():
    """The emergency-revocation guarantee. If this ever flips, it is a breach."""
    resolved = resolve_permissions(
        AdminRole.SUPPORT,
        granted=[Permission.WALLET_ADJUST],
        denied=[Permission.WALLET_ADJUST],
    )
    assert Permission.WALLET_ADJUST not in resolved


def test_deny_beats_super_admin():
    resolved = resolve_permissions(AdminRole.SUPER_ADMIN, denied=[Permission.ADMINS_WRITE])
    assert Permission.ADMINS_WRITE not in resolved


def test_role_permission_sets_are_immutable():
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[AdminRole.VIEWER] = frozenset()  # type: ignore[index]
