"""A volume the customer chose, priced from the volumes we actually sell.

Nobody types a price for 35GB. The shop already says what 20GB and 50GB cost
for each term, and a customer asking for something in between is asking where
on that line they sit. So the price is read off the catalogue rather than off
a separate per-GB tariff an operator would have to keep in step with it:

* **Between two packages** of the same term, the price is the straight line
  between them. 35GB between 20GB at 180k and 50GB at 400k is 290k.
* **Above the largest package**, the largest package's own per-GB rate. Going
  past the catalogue earns no further bulk discount, because the operator
  never offered one.
* **Below the smallest package** is refused. The smallest package is the
  floor of the shop, and a custom volume is not a way under it.

The term is fixed and only the volume moves. Interpolating across terms as
well would invent multi-month discounts the operator did not set.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from geekvpn.domain.catalog.durations import rung_for_days
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan

#: Big enough for any real order, small enough that a typo of three extra
#: zeros is refused rather than quoted and paid for.
MAX_CUSTOM_GIB: Final[int] = 10_000


@dataclass(frozen=True, slots=True)
class VolumePoint:
    """One package of the term being priced: its total volume and price."""

    quota_gib: int
    price: Money


def total_gib(monthly_gib: int, duration_days: int) -> int:
    """The customer picks a monthly volume; a longer term carries more of it.

    The same rule the duration ladder uses when it generates packages, so a
    custom 20GB for three months holds exactly what the 20GB package does.
    """
    return int(monthly_gib * duration_days / 30)


def minimum_gib(points: Sequence[VolumePoint]) -> int:
    if not points:
        raise CatalogValidationError("This term has no volume packages to price from.")
    return min(point.quota_gib for point in points)


def price_for_volume(points: Sequence[VolumePoint], quota_gib: int) -> Money:
    """Price ``quota_gib`` on the line through ``points``."""
    usable = sorted((p for p in points if p.quota_gib > 0), key=lambda p: p.quota_gib)
    if not usable:
        raise CatalogValidationError("This term has no volume packages to price from.")
    floor = usable[0].quota_gib
    if quota_gib > MAX_CUSTOM_GIB:
        raise CatalogValidationError(
            f"بیشترین حجم قابل خرید {MAX_CUSTOM_GIB} گیگه.", quota_gib=quota_gib
        )
    if quota_gib < floor:
        raise CatalogValidationError(
            f"کمترین حجم قابل خرید {floor} گیگه.", quota_gib=quota_gib, minimum=floor
        )

    below = [p for p in usable if p.quota_gib <= quota_gib]
    above = [p for p in usable if p.quota_gib >= quota_gib]
    lower = below[-1]

    if above:
        upper = above[0]
        if upper.quota_gib == lower.quota_gib:
            price = lower.price
        else:
            span = upper.quota_gib - lower.quota_gib
            # Signed arithmetic on purpose: an operator can price a larger
            # package below a smaller one, and the guard below catches that.
            step = upper.price.amount - lower.price.amount
            amount = lower.price.amount + step * (quota_gib - lower.quota_gib) // span
            price = Money.of(max(amount, 0)).round_to()
    else:
        # Past the catalogue: the largest package's rate, scaled.
        price = Money.of(lower.price.amount * quota_gib // lower.quota_gib).round_to()

    # Never cheaper than a package with less in it. Without this, a catalogue
    # where 50GB is on offer below 20GB would sell 30GB for less than 20GB.
    cheapest_allowed = max(p.price for p in below)
    return max(price, cheapest_allowed)


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def custom_plan_name(monthly_gib: int, duration_days: int) -> str:
    """What the order, the invoice and the service card call it.

    Marked as custom so support reading an order can tell at a glance that no
    package of that name exists to look up.
    """
    rung = rung_for_days(duration_days)
    term = rung.name_fa if rung is not None else f"{duration_days} روزه"
    return f"{monthly_gib} گیگ {term} (دلخواه)".translate(_FA_DIGITS)


def custom_plan(anchor: Plan, *, monthly_gib: int, quota_gib: int, price: Money) -> Plan:
    """A one-off package shaped like ``anchor`` with the chosen volume.

    It keeps the anchor's id, product and device limit, so campaigns and
    coupons that target the anchor apply to it, and provisioning places it on
    the same nodes. It is never saved: the order copies its terms.
    """
    return Plan(
        plan_id=anchor.id,
        product_id=anchor.product_id,
        slug=anchor.slug,
        plan_type=anchor.plan_type,
        name_fa=custom_plan_name(monthly_gib, anchor.duration_days),
        duration_days=anchor.duration_days,
        base_price=price,
        quota_gib=quota_gib,
        device_limit=anchor.device_limit,
        # The floor protects the anchor's price; a reseller's retail line can
        # sit under it, and refusing their customer's order for that would be
        # our margin rule breaking their shop.
        min_price=min(anchor.min_price, price),
        cashback_bps=anchor.cashback_bps,
        state=anchor.state,
    )
