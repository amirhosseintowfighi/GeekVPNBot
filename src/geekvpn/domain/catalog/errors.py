"""Catalog and pricing failures.

All of these are expected business outcomes, so they subclass `DomainError` and
carry enough detail for the bot to render a specific Persian message. "Coupon is
invalid" is a support ticket; "this coupon expired on 12 Mordad" is not.
"""

from __future__ import annotations

from geekvpn.domain.base.errors import ConflictError, DomainError, ValidationError


class CatalogError(DomainError):
    code = "catalog_error"
    message = "A catalog error occurred."


class PlanNotPurchasable(CatalogError):
    """The plan exists but cannot be bought right now."""

    code = "plan_not_purchasable"
    message = "This plan is not available for purchase."


class CouponNotApplicable(CatalogError):
    """The coupon is valid but not for this basket.

    Deliberately distinct from expiry and exhaustion so the customer is told
    what to do about it.
    """

    code = "coupon_not_applicable"
    message = "This code does not apply to the selected plan."


class CouponExpired(CatalogError):
    code = "coupon_expired"
    message = "This code has expired."


class CouponExhausted(CatalogError):
    code = "coupon_exhausted"
    message = "This code has reached its usage limit."


class CampaignNotRunning(CatalogError):
    code = "campaign_not_running"
    message = "This campaign is not currently running."


class PriceFloorBreached(CatalogError):
    """Stacked discounts drove the price below the configured floor.

    Raised rather than silently clamped when the floor is breached by a
    *coupon*, because that combination is usually an operator mistake and
    swallowing it means discovering the loss in the monthly numbers.
    """

    code = "price_floor_breached"
    message = "The combined discount is larger than this plan allows."


class CatalogConflict(ConflictError):
    code = "catalog_conflict"
    message = "The catalog entry conflicts with an existing one."


class CatalogValidationError(ValidationError):
    code = "catalog_validation_error"
    message = "The catalog entry is invalid."
