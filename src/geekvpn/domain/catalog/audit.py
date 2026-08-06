"""Audit actions owned by the catalog context.

Declared here rather than appended to the shared Phase 2 ``AuditAction`` enum.
Two reasons:

1. Bounded contexts own their own vocabulary. Every new context appending to
   one central enum turns that enum into a dumping ground and couples every
   context to every other.
2. It keeps Phase 4 purely additive. Nothing in the Phase 2 identity module has
   to change, so there is no migration of an existing enum and no risk to code
   that is already running in production.

These are ``StrEnum`` members, exactly like ``AuditAction``, so the audit
recorder and the ``audit_logs.action`` column accept them unchanged.

Every money-affecting or visibility-affecting change in the catalogue emits
one. "Who dropped the price of Geek Turbo by 40% at 3am" must be answerable.
"""

from __future__ import annotations

from enum import StrEnum


class CatalogAuditAction(StrEnum):
    """Auditable catalog operations, namespaced ``catalog.*``."""

    CATEGORY_CREATED = "catalog.category.created"
    CATEGORY_UPDATED = "catalog.category.updated"
    CATEGORY_STATE_CHANGED = "catalog.category.state_changed"

    PRODUCT_CREATED = "catalog.product.created"
    PRODUCT_UPDATED = "catalog.product.updated"
    PRODUCT_PANEL_BOUND = "catalog.product.panel_bound"
    PRODUCT_PUBLISHED = "catalog.product.published"
    PRODUCT_ARCHIVED = "catalog.product.archived"

    PLAN_CREATED = "catalog.plan.created"
    PLAN_UPDATED = "catalog.plan.updated"
    PLAN_PUBLISHED = "catalog.plan.published"
    PLAN_ARCHIVED = "catalog.plan.archived"
    PLAN_PRICE_CHANGED = "catalog.plan.price_changed"

    COUPON_CREATED = "catalog.coupon.created"
    COUPON_BULK_CREATED = "catalog.coupon.bulk_created"
    COUPON_ARCHIVED = "catalog.coupon.archived"
    COUPON_REDEEMED = "catalog.coupon.redeemed"

    CAMPAIGN_CREATED = "catalog.campaign.created"
    CAMPAIGN_ACTIVATED = "catalog.campaign.activated"
    CAMPAIGN_PAUSED = "catalog.campaign.paused"
    CAMPAIGN_ARCHIVED = "catalog.campaign.archived"
