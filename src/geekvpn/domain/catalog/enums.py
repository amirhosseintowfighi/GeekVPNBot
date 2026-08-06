"""Catalog vocabulary.

Every enum here is stored as its string value, never its ordinal. An ordinal is
a landmine: reordering members silently rewrites the meaning of existing rows.
"""

from __future__ import annotations

import enum


class ProductTier(enum.StrEnum):
    """The quality ladder customers actually choose between.

    This is a *product* concept, not a technical one. It maps onto connection
    quality and therefore onto price, which is why it lives in the domain
    rather than being a free-text marketing label.
    """

    DIRECT = "direct"
    """Direct connection. Cheapest, good enough for browsing."""

    TUNNEL = "tunnel"
    """Tunnelled through an intermediate hop. Lower ping, more stable."""

    ELITE = "elite"
    """Premium tunnel on reserved capacity."""


class PlanType(enum.StrEnum):
    """How a package meters usage.

    These are three genuinely different pricing axes, not cosmetic labels:

    * ``TRAFFIC`` sells a volume that expires on a date. Both limits bind.
    * ``UNLIMITED`` sells time with no volume ceiling at all.
    * ``DURATION`` sells time with a *daily* fair-use ceiling, which is how we
      offer long durations without exposing ourselves to a handful of accounts
      saturating a node.
    """

    TRAFFIC = "traffic"
    UNLIMITED = "unlimited"
    DURATION = "duration"


class PublicationState(enum.StrEnum):
    """Lifecycle of anything shown in the storefront.

    ``ARCHIVED`` is distinct from deletion. A plan that has ever been sold can
    never be deleted, because historical orders reference it and a customer's
    invoice must still render years later.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"

    @property
    def is_visible(self) -> bool:
        return self is PublicationState.PUBLISHED


class DiscountKind(enum.StrEnum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class CouponKind(enum.StrEnum):
    """Who may redeem a coupon, and how often."""

    PUBLIC = "public"
    """Anyone with the code, subject to the usage caps."""

    SINGLE_USE = "single_use"
    """Burned globally after one successful redemption."""

    PER_USER = "per_user"
    """Each customer may redeem once."""

    TARGETED = "targeted"
    """Bound to one specific customer. Used for support goodwill."""


class CampaignKind(enum.StrEnum):
    """Automatic, code-free promotions.

    A flash sale is a campaign with a short window and usually a stock limit;
    modelling it as a separate aggregate would duplicate every field and every
    overlap rule for no gain.
    """

    SEASONAL = "seasonal"
    FLASH_SALE = "flash_sale"
    LAUNCH = "launch"
    WINBACK = "winback"


class RewardTrigger(enum.StrEnum):
    """What causes wallet credit to accrue."""

    REFERRAL_SIGNUP = "referral_signup"
    REFERRAL_FIRST_PURCHASE = "referral_first_purchase"
    PURCHASE_CASHBACK = "purchase_cashback"
