"""RBAC: roles, permissions, and how they resolve.

Design
------
* A **permission** is a fine-grained, namespaced verb on a resource
  (`users.suspend`). Code checks permissions, never roles.
* A **role** is a named bundle of permissions. Roles exist for humans;
  permissions exist for code. This is what lets us add a role later without
  touching a single authorisation check.
* An admin may additionally be **granted** or **denied** individual
  permissions. **Deny always wins**, including over `SUPER_ADMIN`, so an
  emergency revocation is one row and takes effect on the next access token.

Why not string-matching wildcards at check time: wildcards make it impossible
to answer "who can do X?" without evaluating every rule. Explicit sets are
auditable.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from types import MappingProxyType


class Permission(enum.StrEnum):
    """Every privileged action in the platform.

    Phase 2 defines the whole vocabulary up front, including permissions for
    features that do not exist yet, because retro-fitting permissions onto
    shipped endpoints is how systems end up with `is_admin` checks everywhere.
    """

    # Customers
    USERS_READ = "users.read"
    USERS_WRITE = "users.write"
    USERS_SUSPEND = "users.suspend"
    USERS_IMPERSONATE = "users.impersonate"

    # Administrators
    ADMINS_READ = "admins.read"
    ADMINS_WRITE = "admins.write"

    # Commerce (Phase 3+)
    PACKAGES_READ = "packages.read"
    PACKAGES_WRITE = "packages.write"
    ORDERS_READ = "orders.read"
    ORDERS_REFUND = "orders.refund"
    PAYMENTS_READ = "payments.read"
    PAYMENTS_APPROVE = "payments.approve"
    WALLET_READ = "wallet.read"
    WALLET_ADJUST = "wallet.adjust"

    # Fleet
    PANELS_READ = "panels.read"
    PANELS_WRITE = "panels.write"
    SUBSCRIPTIONS_READ = "subscriptions.read"
    SUBSCRIPTIONS_WRITE = "subscriptions.write"

    # Support
    TICKETS_READ = "tickets.read"
    TICKETS_REPLY = "tickets.reply"
    TICKETS_ASSIGN = "tickets.assign"

    # Growth
    # `.read`, so VIEWER picks it up through the suffix rule below rather than
    # needing another explicit entry in the matrix.
    BROADCAST_READ = "broadcast.read"
    BROADCAST_SEND = "broadcast.send"
    CAMPAIGNS_WRITE = "campaigns.write"

    # Analytics
    ANALYTICS_VIEW = "analytics.view"
    ANALYTICS_EXPORT = "analytics.export"

    # Resellers
    RESELLERS_READ = "resellers.read"
    RESELLERS_WRITE = "resellers.write"

    # Platform
    AUDIT_READ = "audit.read"
    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"
    METRICS_READ = "metrics.read"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_READ_ONLY: frozenset[Permission] = frozenset(
    permission for permission in Permission if permission.value.endswith(".read")
)


class AdminRole(enum.StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    FINANCE = "finance"
    SUPPORT = "support"
    VIEWER = "viewer"
    #: Not a member of staff. A reseller signs in through the same door with a
    #: role that resolves to almost nothing, and every endpoint they can reach
    #: additionally scopes its query to their own reseller id. The role says
    #: what kind of action is allowed; the scoping says whose rows.
    RESELLER = "reseller"


_ROLE_PERMISSIONS: dict[AdminRole, frozenset[Permission]] = {
    AdminRole.SUPER_ADMIN: ALL_PERMISSIONS,
    AdminRole.ADMIN: ALL_PERMISSIONS
    - {
        # Only a super admin may create administrators, change platform
        # settings, or impersonate a customer.
        Permission.ADMINS_WRITE,
        Permission.SETTINGS_WRITE,
        Permission.USERS_IMPERSONATE,
    },
    AdminRole.FINANCE: frozenset(
        {
            Permission.USERS_READ,
            Permission.ORDERS_READ,
            Permission.ORDERS_REFUND,
            Permission.PAYMENTS_READ,
            Permission.PAYMENTS_APPROVE,
            Permission.WALLET_READ,
            Permission.WALLET_ADJUST,
            Permission.PACKAGES_READ,
            Permission.METRICS_READ,
            Permission.ANALYTICS_VIEW,
            Permission.ANALYTICS_EXPORT,
        }
    ),
    AdminRole.SUPPORT: frozenset(
        {
            Permission.USERS_READ,
            Permission.USERS_SUSPEND,
            Permission.ORDERS_READ,
            Permission.PAYMENTS_READ,
            Permission.PACKAGES_READ,
            Permission.SUBSCRIPTIONS_READ,
            Permission.SUBSCRIPTIONS_WRITE,
            Permission.TICKETS_READ,
            Permission.TICKETS_REPLY,
            Permission.TICKETS_ASSIGN,
        }
    ),
    # VIEWER is derived from the ``.read`` suffix, and "analytics.view" does
    # not end in ".read". Adding it explicitly is cheaper than renaming a
    # permission the admin panel already ships.
    AdminRole.VIEWER: (_READ_ONLY - {Permission.AUDIT_READ}) | {Permission.ANALYTICS_VIEW},
    # Deliberately small, and deliberately *not* derived from the read-only
    # suffix rule: a reseller must not pick up `admins.read`, `settings.read`
    # or `payments.read` by the accident of a naming convention.
    #
    # Every one of these is additionally scoped to their own rows at the
    # endpoint. `users.read` here means "the customers I created", never the
    # platform's customer list - and that is enforced by the query, because a
    # permission set cannot express whose.
    AdminRole.RESELLER: frozenset(
        {
            Permission.USERS_READ,
            Permission.PACKAGES_READ,
            Permission.SUBSCRIPTIONS_READ,
            Permission.SUBSCRIPTIONS_WRITE,
            Permission.ORDERS_READ,
            Permission.WALLET_READ,
            Permission.TICKETS_READ,
            Permission.TICKETS_REPLY,
        }
    ),
}

# Read-only view: a mutable module-level dict is an accident waiting to happen.
ROLE_PERMISSIONS = MappingProxyType(_ROLE_PERMISSIONS)


def permissions_for_role(role: AdminRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def resolve_permissions(
    role: AdminRole,
    *,
    granted: Iterable[Permission] = (),
    denied: Iterable[Permission] = (),
) -> frozenset[Permission]:
    """Effective permission set for an admin.

    Order of evaluation: role baseline, then explicit grants, then explicit
    denials. Denial is last and therefore absolute.
    """
    effective = set(permissions_for_role(role))
    effective |= set(granted)
    effective -= set(denied)
    return frozenset(effective)
