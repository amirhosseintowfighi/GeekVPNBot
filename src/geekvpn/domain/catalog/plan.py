"""Plans: the ready-made packages customers actually buy.

This is the heart of the product decision made during discovery. A plan is a
**complete, pre-priced bundle**: "Geek Turbo, one month, 50 GB, 190,000 Toman".
The customer picks one and pays. There is no volume slider, no mid-cycle
top-up, and no per-gigabyte meter.

That is enforced structurally rather than by convention. A `Plan` has no API for
adding traffic to a live subscription, so no future feature can accidentally
grow one - it would have to be a deliberate new aggregate, at which point
somebody will ask why.

The three plan types are three different pricing axes, and each has its own
invariants. Encoding them as one class with a discriminator plus validation,
rather than three subclasses, is deliberate: the storefront, the pricing engine
and the admin panel all treat plans uniformly, and polymorphism there would buy
nothing while making the repository mapping significantly worse.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.enums import PlanType, PublicationState
from geekvpn.domain.catalog.errors import CatalogValidationError, PlanNotPurchasable
from geekvpn.domain.catalog.events import PlanPriceChanged, PlanPublished
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.slug import validate_slug

BYTES_PER_GIB = 1024**3
MAX_DURATION_DAYS = 3650
MAX_CASHBACK_BPS = 3_000
"""30%. A cashback rate above this is almost certainly a misplaced decimal, and
the damage compounds silently across every order until someone reads a report."""


class Plan(AggregateRoot[uuid.UUID]):
    """A purchasable package."""

    __slots__ = (
        "badge_fa",
        "base_price",
        "cashback_bps",
        "compare_at_price",
        "created_at",
        "daily_quota_gib",
        "description_fa",
        "device_limit",
        "duration_days",
        "is_featured",
        "max_per_user",
        "min_price",
        "name_fa",
        "plan_type",
        "product_id",
        "quota_gib",
        "slug",
        "sort_order",
        "state",
    )

    def __init__(
        self,
        *,
        plan_id: uuid.UUID,
        product_id: uuid.UUID,
        slug: str,
        plan_type: PlanType,
        name_fa: str,
        duration_days: int,
        base_price: Money,
        quota_gib: int | None = None,
        daily_quota_gib: int | None = None,
        description_fa: str | None = None,
        badge_fa: str | None = None,
        device_limit: int = 2,
        compare_at_price: Money | None = None,
        min_price: Money | None = None,
        cashback_bps: int = 0,
        max_per_user: int | None = None,
        sort_order: int = 0,
        state: PublicationState = PublicationState.DRAFT,
        is_featured: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(plan_id)
        self.product_id = product_id
        self.slug = validate_slug(slug, field="plan slug")
        self.plan_type = plan_type
        self.name_fa = _require_text(name_fa, field="name_fa", limit=96)
        self.description_fa = description_fa
        self.badge_fa = badge_fa
        self.duration_days = _validate_duration(duration_days)
        self.quota_gib = quota_gib
        self.daily_quota_gib = daily_quota_gib
        self.device_limit = _validate_device_limit(device_limit)
        self.base_price = base_price
        self.compare_at_price = compare_at_price
        self.min_price = min_price or Money.zero()
        self.cashback_bps = _validate_cashback(cashback_bps)
        self.max_per_user = max_per_user
        self.sort_order = sort_order
        self.state = state
        self.is_featured = is_featured
        self.created_at = created_at

        self._validate_type_invariants()
        self._validate_price_invariants()

    # -- invariants --------------------------------------------------------

    def revalidate(self) -> None:
        """Re-check every invariant after a batch of field assignments.

        The admin update path mutates several fields before saving. Validating
        after each individual assignment would reject legitimate edits that are
        only valid once all of them have landed - for example lowering
        ``min_price`` and ``base_price`` together. So the aggregate exposes one
        explicit checkpoint, and the service is required to call it before the
        repository sees the object.
        """
        self._validate_type_invariants()
        self._validate_price_invariants()
        _validate_duration(self.duration_days)
        _validate_device_limit(self.device_limit)
        _validate_cashback(self.cashback_bps)

    def _validate_type_invariants(self) -> None:
        """Each plan type binds exactly the quota fields that make sense for it.

        Leaving an irrelevant field populated is not harmless: a TRAFFIC plan
        that also carries a daily cap would be silently enforced by some panels
        and ignored by others, producing a support ticket we cannot reproduce.
        """
        if self.plan_type is PlanType.TRAFFIC:
            if self.quota_gib is None or self.quota_gib <= 0:
                raise CatalogValidationError(
                    "A traffic plan must define a positive volume in GiB.",
                    plan_type=self.plan_type.value,
                    quota_gib=self.quota_gib,
                )
            if self.daily_quota_gib is not None:
                raise CatalogValidationError(
                    "A traffic plan must not define a daily cap; use a duration plan for that.",
                    plan_type=self.plan_type.value,
                )

        elif self.plan_type is PlanType.UNLIMITED:
            if self.quota_gib is not None or self.daily_quota_gib is not None:
                raise CatalogValidationError(
                    "An unlimited plan must not define any volume cap.",
                    plan_type=self.plan_type.value,
                )

        elif self.plan_type is PlanType.DURATION:
            if self.daily_quota_gib is None or self.daily_quota_gib <= 0:
                raise CatalogValidationError(
                    "A duration plan must define a positive daily fair-use cap.",
                    plan_type=self.plan_type.value,
                    daily_quota_gib=self.daily_quota_gib,
                )
            if self.quota_gib is not None:
                raise CatalogValidationError(
                    "A duration plan caps usage per day, not in total.",
                    plan_type=self.plan_type.value,
                )

    def _validate_price_invariants(self) -> None:
        if self.min_price > self.base_price:
            raise CatalogValidationError(
                "The price floor cannot exceed the base price.",
                base_price=self.base_price.amount,
                min_price=self.min_price.amount,
            )
        if self.compare_at_price is not None and self.compare_at_price <= self.base_price:
            # A strike-through price that is not higher than the real price is
            # dishonest signalling, and in several jurisdictions illegal.
            raise CatalogValidationError(
                "The compare-at price must be higher than the base price.",
                base_price=self.base_price.amount,
                compare_at_price=self.compare_at_price.amount,
            )

    # -- derived values ----------------------------------------------------

    @property
    def is_visible(self) -> bool:
        return self.state.is_visible

    @property
    def is_unlimited(self) -> bool:
        return self.plan_type is PlanType.UNLIMITED

    @property
    def total_quota_bytes(self) -> int | None:
        """Total volume in bytes, or ``None`` when uncapped.

        Bytes, because that is the unit every panel adapter speaks. Converting
        here rather than at each call site means the 1024-vs-1000 decision is
        made exactly once.
        """
        if self.plan_type is PlanType.TRAFFIC and self.quota_gib is not None:
            return self.quota_gib * BYTES_PER_GIB
        if self.plan_type is PlanType.DURATION and self.daily_quota_gib is not None:
            return self.daily_quota_gib * self.duration_days * BYTES_PER_GIB
        return None

    @property
    def price_per_gib(self) -> int | None:
        """Unit economics, for the admin panel's margin column."""
        quota = self.total_quota_bytes
        if not quota:
            return None
        return round(self.base_price.amount / (quota / BYTES_PER_GIB))

    @property
    def savings_bps(self) -> int:
        """How much the compare-at price implies, in basis points."""
        if self.compare_at_price is None or self.compare_at_price.is_zero:
            return 0
        saved = self.compare_at_price.amount - self.base_price.amount
        return (saved * 10_000) // self.compare_at_price.amount

    # -- behaviour ---------------------------------------------------------

    def assert_purchasable(self) -> None:
        if not self.is_visible:
            raise PlanNotPurchasable(
                "This plan is not currently on sale.",
                plan_id=str(self.id),
                state=self.state.value,
            )

    def publish(self) -> None:
        self.state = PublicationState.PUBLISHED
        self.record(
            PlanPublished(
                plan_id=self.id,
                product_id=self.product_id,
                slug=self.slug,
                price=self.base_price.amount,
            )
        )

    def archive(self) -> None:
        """Archived plans stay readable forever; historical orders point at them."""
        self.state = PublicationState.ARCHIVED

    def change_price(self, new_price: Money, *, changed_by: uuid.UUID | None = None) -> None:
        if new_price == self.base_price:
            return
        if new_price < self.min_price:
            raise CatalogValidationError(
                "The new price is below this plan's floor.",
                new_price=new_price.amount,
                min_price=self.min_price.amount,
            )
        old = self.base_price
        self.base_price = new_price
        if self.compare_at_price is not None and self.compare_at_price <= new_price:
            # Keep the strike-through honest after a price rise.
            self.compare_at_price = None
        self.record(
            PlanPriceChanged(
                plan_id=self.id,
                old_price=old.amount,
                new_price=new_price.amount,
                changed_by=changed_by,
            )
        )


def _validate_duration(days: int) -> int:
    if days <= 0:
        raise CatalogValidationError("Duration must be at least one day.", duration_days=days)
    if days > MAX_DURATION_DAYS:
        raise CatalogValidationError(
            f"Duration must be at most {MAX_DURATION_DAYS} days.", duration_days=days
        )
    return days


def _validate_device_limit(limit: int) -> int:
    if limit < 1:
        raise CatalogValidationError("A plan must allow at least one device.", device_limit=limit)
    return limit


def _validate_cashback(bps: int) -> int:
    if bps < 0:
        raise CatalogValidationError("Cashback cannot be negative.", cashback_bps=bps)
    if bps > MAX_CASHBACK_BPS:
        raise CatalogValidationError(
            "Cashback above 30% is almost certainly a mistake.", cashback_bps=bps
        )
    return bps


def _require_text(value: str, *, field: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise CatalogValidationError(f"{field} is required.", field=field)
    if len(text) > limit:
        raise CatalogValidationError(
            f"{field} must be at most {limit} characters.",
            field=field,
            length=len(text),
        )
    return text
