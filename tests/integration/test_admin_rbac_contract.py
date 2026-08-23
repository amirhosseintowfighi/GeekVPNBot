"""The admin panel and the backend must agree on the *names* of things.

The panel had built its own vocabulary. Roles it called `owner`, the API calls
`super_admin`. Permissions it called `users.view`, the API calls `users.read`.
Not one name matched, and because the panel's permission check denies anything
it does not recognise, a super admin who signed in correctly was refused every
screen in the product - "این بخش برای نقش شما فعال نیست" on the dashboard, on
tickets, on everything.

A reviewer cannot catch this by reading either side alone, and neither side's
tests could: the panel's RBAC suite passed in full, asserting the behaviour of
a matrix no real session could ever reach. So it is pinned here, where both
vocabularies are in scope at once.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from geekvpn.domain.identity.permissions import AdminRole, Permission

pytestmark = pytest.mark.integration

ADMIN_SRC = Path(__file__).resolve().parents[2] / "admin" / "src"
RBAC_TS = ADMIN_SRC / "lib" / "rbac.ts"

#: Permission-shaped strings in the panel that are not permissions.
_NOT_PERMISSIONS = frozenset()


def _string_array(source: str, name: str) -> list[str]:
    """The string literals of an `export const NAME = [...] as const`."""
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.DOTALL)
    assert match, f"{name} is not declared in rbac.ts in the expected shape"
    return re.findall(r"'([^']+)'", match.group(1))


def test_the_panel_and_the_api_name_the_same_roles() -> None:
    roles = set(_string_array(RBAC_TS.read_text(encoding="utf-8"), "ROLES"))

    assert roles == {role.value for role in AdminRole}


def test_the_panel_and_the_api_name_the_same_permissions() -> None:
    permissions = set(_string_array(RBAC_TS.read_text(encoding="utf-8"), "PERMISSIONS"))

    assert permissions == {permission.value for permission in Permission}


def test_every_permission_the_screens_ask_for_is_one_the_api_can_grant() -> None:
    """The assertion that would have caught it.

    `rbac.ts` agreeing with the API is not enough on its own: the screens call
    `can('...')` with string literals, and a name that exists in neither place
    fails silently as a denial.
    """
    known = {permission.value for permission in Permission}
    unknown: dict[str, set[str]] = {}

    for file in list(ADMIN_SRC.rglob("*.ts")) + list(ADMIN_SRC.rglob("*.tsx")):
        if file == RBAC_TS:
            continue
        source = file.read_text(encoding="utf-8")
        asked = set(re.findall(r"can(?:Any|All)?\(\s*'([a-z_]+\.[a-z_]+)'", source))
        asked |= set(re.findall(r"\bpermission: '([a-z_]+\.[a-z_]+)'", source))
        asked |= set(re.findall(r'\bpermission="([a-z_]+\.[a-z_]+)"', source))
        stray = asked - known - _NOT_PERMISSIONS
        if stray:
            unknown[file.relative_to(ADMIN_SRC).as_posix()] = stray

    assert not unknown, f"permissions the API has never heard of: {unknown}"
