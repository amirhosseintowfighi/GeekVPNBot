"""Audit log entries.

Rules that make an audit log worth having:

1. **Append-only.** No update, no delete. Enforced at the database level in
   Phase 2's migration, not by convention.
2. **Always answers five questions**: who, what, to what, from where, when.
3. **Records failures too.** A rejected privilege escalation is more
   interesting than a successful one.
4. **Carries the correlation id**, so an audit row links to the exact request
   log lines that produced it.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from geekvpn.domain.identity.enums import SubjectType


class AuditAction(enum.StrEnum):
    """Auditable actions.

    Namespaced identically to permissions so a reviewer can grep one term and
    find both "who is allowed" and "who actually did it".
    """

    # Authentication
    AUTH_LOGIN_SUCCEEDED = "auth.login.succeeded"
    AUTH_LOGIN_FAILED = "auth.login.failed"
    AUTH_LOGOUT = "auth.logout"
    AUTH_LOGOUT_ALL = "auth.logout_all"
    AUTH_TOKEN_REFRESHED = "auth.token.refreshed"  # noqa: S105 - a constant name, not a credential
    AUTH_TOKEN_REUSE_DETECTED = "auth.token.reuse_detected"  # noqa: S105 - a constant name, not a credential
    AUTH_ACCOUNT_LOCKED = "auth.account.locked"
    AUTH_TOTP_ENABLED = "auth.totp.enabled"
    AUTH_TOTP_DISABLED = "auth.totp.disabled"
    AUTH_TOTP_FAILED = "auth.totp.failed"
    AUTH_PERMISSION_DENIED = "auth.permission.denied"
    AUTH_IP_REJECTED = "auth.ip.rejected"

    # Identity administration
    USER_REGISTERED = "user.registered"
    USER_SUSPENDED = "user.suspended"
    USER_REINSTATED = "user.reinstated"
    ADMIN_CREATED = "admin.created"
    ADMIN_UPDATED = "admin.updated"
    ADMIN_ROLE_CHANGED = "admin.role.changed"
    ADMIN_PERMISSIONS_CHANGED = "admin.permissions.changed"
    ADMIN_PASSWORD_CHANGED = "admin.password.changed"  # noqa: S105 - a constant name, not a credential
    ADMIN_DISABLED = "admin.disabled"
    SESSION_REVOKED = "session.revoked"

    # Platform
    SETTING_CHANGED = "setting.changed"

    # Catalog and pricing
    CATEGORY_CREATED = "catalog.category.created"
    CATEGORY_UPDATED = "catalog.category.updated"
    PRODUCT_CREATED = "catalog.product.created"
    PRODUCT_UPDATED = "catalog.product.updated"
    PRODUCT_PUBLISHED = "catalog.product.published"
    PRODUCT_ARCHIVED = "catalog.product.archived"
    PLAN_CREATED = "catalog.plan.created"
    PLAN_UPDATED = "catalog.plan.updated"
    PLAN_PUBLISHED = "catalog.plan.published"
    PLAN_ARCHIVED = "catalog.plan.archived"
    PLAN_PRICE_CHANGED = "catalog.plan.price_changed"
    COUPON_CREATED = "catalog.coupon.created"
    COUPON_UPDATED = "catalog.coupon.updated"
    COUPON_ARCHIVED = "catalog.coupon.archived"
    COUPON_REDEEMED = "catalog.coupon.redeemed"
    CAMPAIGN_CREATED = "catalog.campaign.created"
    CAMPAIGN_UPDATED = "catalog.campaign.updated"
    CAMPAIGN_ACTIVATED = "catalog.campaign.activated"
    CAMPAIGN_PAUSED = "catalog.campaign.paused"
    CAMPAIGN_ARCHIVED = "catalog.campaign.archived"


class AuditOutcome(enum.StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One immutable fact about something that happened."""

    id: uuid.UUID
    #: `AuditAction` for anything this module names, and a plain string
    #: for anything another subsystem recorded - the catalogue writes its
    #: own `CatalogAuditAction` into the same column, by design, and a
    #: release that adds an action leaves rows an older reader has never
    #: heard of. History has to stay readable either way.
    action: AuditAction | str
    outcome: AuditOutcome
    occurred_at: datetime
    actor_type: SubjectType
    actor_id: uuid.UUID | None = None
    actor_label: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
