"""Campaigns and flash sales: automatic, code-free promotions.

A flash sale is a campaign whose window is short and whose stock is limited. It
is not a separate aggregate, because it would need every field a campaign has,
plus the identical overlap and priority rules. One aggregate with a `kind`
discriminator means a bug in stock handling is fixed once.

**Only one campaign ever applies to a given plan.** When several match, the one
with the highest priority wins, ties broken by the largest discount. Stacking
campaigns is how a 30% seasonal sale plus a 40% flash sale becomes a 58%
giveaway that nobody authorised.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import CampaignKind, PublicationState
from geekvpn.domain.catalog.errors import CampaignNotRunning, CatalogValidationError
from geekvpn.domain.catalog.events import CampaignStarted
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.scope import PromotionScope, PromotionTarget
from geekvpn.domain.catalog.slug import validate_slug
from geekvpn.domain.catalog.window import TimeWindow


class Campaign(AggregateRoot[uuid.UUID]):
    """An automatic discount applied without the customer typing anything."""

    __slots__ = (
        "banner_url",
        "created_at",
        "created_by",
        "description_fa",
        "discount",
        "kind",
        "max_redemptions",
        "name_fa",
        "priority",
        "redemption_count",
        "scope",
        "slug",
        "state",
        "window",
    )

    def __init__(
        self,
        *,
        campaign_id: uuid.UUID,
        slug: str,
        kind: CampaignKind,
        name_fa: str,
        discount: Discount,
        window: TimeWindow,
        scope: PromotionScope | None = None,
        description_fa: str | None = None,
        banner_url: str | None = None,
        max_redemptions: int | None = None,
        redemption_count: int = 0,
        priority: int = 0,
        state: PublicationState = PublicationState.DRAFT,
        created_by: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(campaign_id)
        self.slug = validate_slug(slug, field="campaign slug")
        self.kind = kind
        self.name_fa = name_fa.strip()
        self.description_fa = description_fa
        self.banner_url = banner_url
        self.discount = discount
        self.window = window
        self.scope = scope or PromotionScope()
        self.max_redemptions = max_redemptions
        self.redemption_count = redemption_count
        self.priority = priority
        self.state = state
        self.created_by = created_by
        self.created_at = created_at

        if not self.name_fa:
            raise CatalogValidationError("A campaign needs a name.", field="name_fa")
        if kind is CampaignKind.FLASH_SALE and window.ends_at is None:
            # A flash sale without an end is just a price cut, and it will be
            # forgotten. Forcing an end date is a guard rail against margin
            # quietly evaporating.
            raise CatalogValidationError("A flash sale must have an end time.", slug=self.slug)

    # -- state -------------------------------------------------------------

    @property
    def is_sold_out(self) -> bool:
        return self.max_redemptions is not None and self.redemption_count >= self.max_redemptions

    @property
    def remaining_stock(self) -> int | None:
        """Powers the "only 12 left" urgency badge."""
        if self.max_redemptions is None:
            return None
        return max(0, self.max_redemptions - self.redemption_count)

    def is_running(self, now: datetime) -> bool:
        return self.state.is_visible and self.window.contains(now) and not self.is_sold_out

    def applies_to(self, target: PromotionTarget, *, now: datetime) -> bool:
        return self.is_running(now) and self.scope.matches(
            plan_id=target.plan_id,
            product_id=target.product_id,
            tier=target.tier,
        )

    def seconds_remaining(self, now: datetime) -> int | None:
        """Seconds until the campaign closes, or None if it never does.

        The Mini App renders a countdown on flash-sale cards; it should not have
        to reach through to `campaign.window` to find the number.
        """
        return self.window.seconds_remaining(now)

    def discount_for(self, subtotal: Money) -> Money:
        return self.discount.compute(subtotal)

    # -- behaviour ---------------------------------------------------------

    def activate(self) -> None:
        self.state = PublicationState.PUBLISHED
        self.record(CampaignStarted(campaign_id=self.id, slug=self.slug, kind=self.kind.value))

    def pause(self) -> None:
        self.state = PublicationState.DRAFT

    def archive(self) -> None:
        self.state = PublicationState.ARCHIVED

    def consume(self, *, now: datetime, quantity: int = 1) -> None:
        """Record redemptions against the stock limit.

        Called only after an order is confirmed. The database enforces the
        ceiling too - see the check constraint on `campaigns` - because two
        concurrent buyers of the last flash-sale slot will both pass this check
        before either commits.
        """
        if not self.is_running(now):
            raise CampaignNotRunning(
                "This campaign is no longer running.",
                campaign_id=str(self.id),
                slug=self.slug,
            )
        self.redemption_count += quantity


def best_campaign(
    campaigns: list[Campaign],
    *,
    target: PromotionTarget,
    subtotal: Money,
    now: datetime,
) -> Campaign | None:
    """Pick the single campaign that applies.

    Highest priority wins so operators can force a specific sale to the front.
    Ties are broken by the largest actual discount on *this* subtotal, not by
    the nominal rate: a capped 50% can be worth less than an uncapped 30%, and
    the customer should get whichever is genuinely better.
    """
    eligible = [c for c in campaigns if c.applies_to(target, now=now)]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda c: (c.priority, c.discount_for(subtotal).amount, c.id.int),
    )
