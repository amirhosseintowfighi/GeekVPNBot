"""Admin CRUD over coupons and campaigns.

Split from `CatalogAdminService` on purpose. Promotions are a different job
with a different permission (`CAMPAIGNS_WRITE` rather than `PACKAGES_WRITE`):
a marketing operator should be able to launch a flash sale without also being
able to rewrite the product catalogue.
"""

from __future__ import annotations

import uuid
from typing import Any

from geekvpn.application.catalog.commands import (
    CreateCampaignCommand,
    CreateCouponCommand,
    ScopeCommand,
)
from geekvpn.application.ports.catalog import CampaignRepository, CouponRepository
from geekvpn.application.ports.catalog_audit import CatalogAuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.catalog.audit import CatalogAuditAction
from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.coupon import Coupon, normalise_code
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import DiscountKind, PublicationState
from geekvpn.domain.catalog.errors import CatalogConflict, CatalogValidationError
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.scope import PromotionScope
from geekvpn.domain.catalog.window import TimeWindow

#: Enough for an influencer drop, small enough that a typo cannot generate a
#: million rows in one request.
MAX_BULK_COUPONS = 500


def _build_discount(kind: DiscountKind, value: int, max_discount: int | None) -> Discount:
    """``max_discount`` arrives as a plain int from the API and is money."""
    if kind is DiscountKind.PERCENTAGE:
        cap = None if max_discount is None else Money(max_discount)
        return Discount.percentage(value, cap=cap)
    return Discount.fixed(value)


def _build_scope(command: ScopeCommand) -> PromotionScope:
    return PromotionScope(
        plan_ids=frozenset(command.plan_ids),
        product_ids=frozenset(command.product_ids),
        tiers=frozenset(command.tiers),
    )


class PromotionAdminService:
    def __init__(
        self,
        *,
        coupons: CouponRepository,
        campaigns: CampaignRepository,
        clock: Clock,
        audit: CatalogAuditRecorder,
    ) -> None:
        self._coupons = coupons
        self._campaigns = campaigns
        self._clock = clock
        self._audit = audit

    # -- coupons -----------------------------------------------------------

    async def list_coupons(
        self, *, active_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Coupon]:
        return list(
            await self._coupons.list_all(active_only=active_only, limit=limit, offset=offset)
        )

    async def create_coupon(
        self, command: CreateCouponCommand, *, actor_id: uuid.UUID | None = None
    ) -> Coupon:
        code = normalise_code(command.code)
        if await self._coupons.get_by_code(code) is not None:
            raise CatalogConflict("This coupon code already exists.", code=code)

        coupon = self._build_coupon(command, code=code, actor_id=actor_id)
        await self._coupons.add(coupon)
        await self._record(CatalogAuditAction.COUPON_CREATED, coupon.id, actor_id, code=coupon.code)
        return coupon

    async def bulk_create_coupons(
        self,
        template: CreateCouponCommand,
        *,
        count: int,
        prefix: str,
        actor_id: uuid.UUID | None = None,
    ) -> list[Coupon]:
        """Generate a batch of unique single-use codes from one template.

        The use case is an influencer campaign: 200 personal codes, each usable
        once, all tracked back to one drop. Generating them by hand through the
        single-create endpoint is 200 requests and a guaranteed collision.
        """
        if not 1 <= count <= MAX_BULK_COUPONS:
            raise CatalogValidationError(
                f"Bulk creation supports between 1 and {MAX_BULK_COUPONS} coupons.",
                count=count,
            )

        created: list[Coupon] = []
        for _ in range(count):
            # 8 hex characters: collision-free in practice at this batch size,
            # and still short enough to read out over the phone.
            suffix = uuid.uuid4().hex[:8].upper()
            code = normalise_code(f"{prefix}-{suffix}")
            if await self._coupons.get_by_code(code) is not None:
                continue
            coupon = self._build_coupon(template, code=code, actor_id=actor_id)
            await self._coupons.add(coupon)
            created.append(coupon)

        await self._audit.record(
            CatalogAuditAction.COUPON_BULK_CREATED,
            actor_id=actor_id,
            target_type="catalog",
            target_id=prefix,
            requested=count,
            created=len(created),
        )
        return created

    async def archive_coupon(
        self, coupon_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Coupon:
        coupon = await self._coupons.get(coupon_id)
        if coupon is None:
            raise NotFoundError("Coupon not found.", coupon_id=str(coupon_id))
        coupon.archive()
        await self._coupons.update(coupon)
        await self._record(
            CatalogAuditAction.COUPON_ARCHIVED, coupon.id, actor_id, code=coupon.code
        )
        return coupon

    # -- campaigns ---------------------------------------------------------

    async def list_campaigns(
        self, *, limit: int = 50, offset: int = 0, include_archived: bool = False
    ) -> list[Campaign]:
        """Archived campaigns are hidden unless asked for.

        Archiving is how a campaign is removed - one referenced by a
        historical order must not be deleted, or an old invoice becomes an
        unexplainable discount - but "removed" has to mean gone from the
        screen, or the button looks like it did nothing.
        """
        return list(
            await self._campaigns.list_all(
                limit=limit, offset=offset, include_archived=include_archived
            )
        )

    async def create_campaign(
        self, command: CreateCampaignCommand, *, actor_id: uuid.UUID | None = None
    ) -> Campaign:
        if await self._campaigns.get_by_slug(command.slug) is not None:
            raise CatalogConflict("A campaign with this slug already exists.", slug=command.slug)

        campaign = Campaign(
            campaign_id=uuid.uuid4(),
            slug=command.slug,
            kind=command.kind,
            name_fa=command.name_fa,
            discount=_build_discount(
                command.discount_kind, command.discount_value, command.max_discount
            ),
            window=TimeWindow(starts_at=command.starts_at, ends_at=command.ends_at),
            scope=_build_scope(command.scope),
            description_fa=command.description_fa,
            banner_url=command.banner_url,
            max_redemptions=command.max_redemptions,
            priority=command.priority,
            created_by=actor_id,
        )
        await self._campaigns.add(campaign)
        await self._record(
            CatalogAuditAction.CAMPAIGN_CREATED,
            campaign.id,
            actor_id,
            slug=campaign.slug,
            kind=campaign.kind.value,
        )
        return campaign

    async def set_campaign_state(
        self, campaign_id: uuid.UUID, *, state: str, actor_id: uuid.UUID | None = None
    ) -> Campaign:
        campaign = await self._require_campaign(campaign_id)

        if state == "activate":
            campaign.activate()
            action = CatalogAuditAction.CAMPAIGN_ACTIVATED
        elif state == "pause":
            campaign.pause()
            action = CatalogAuditAction.CAMPAIGN_PAUSED
        elif state == "archive":
            campaign.archive()
            action = CatalogAuditAction.CAMPAIGN_ARCHIVED
        else:
            raise CatalogValidationError(
                "State must be one of: activate, pause, archive.", state=state
            )

        await self._campaigns.update(campaign)
        await self._record(action, campaign.id, actor_id, state=state)
        return campaign

    async def campaign_performance(self, campaign_id: uuid.UUID) -> dict[str, Any]:
        """Live counters for the admin dashboard.

        Deliberately cheap - it reads only the aggregate, no order joins - so
        the campaigns screen can poll it while a flash sale is running.
        """
        campaign = await self._require_campaign(campaign_id)
        now = self._clock.now()
        return {
            "slug": campaign.slug,
            "name": campaign.name_fa,
            "state": campaign.state.value,
            "is_running": campaign.is_running(now),
            "redemptions": campaign.redemption_count,
            "remaining_stock": campaign.remaining_stock,
            "is_sold_out": campaign.is_sold_out,
            "seconds_remaining": campaign.seconds_remaining(now),
        }

    # -- internals ---------------------------------------------------------

    def _build_coupon(
        self, command: CreateCouponCommand, *, code: str, actor_id: uuid.UUID | None
    ) -> Coupon:
        return Coupon(
            coupon_id=uuid.uuid4(),
            code=code,
            kind=command.kind,
            discount=_build_discount(
                command.discount_kind, command.discount_value, command.max_discount
            ),
            window=TimeWindow(starts_at=command.starts_at, ends_at=command.ends_at),
            scope=_build_scope(command.scope),
            description_fa=command.description_fa,
            max_redemptions=command.max_redemptions,
            max_per_user=command.max_per_user,
            # 0 means "no minimum", which the domain expresses as None.
            min_order_amount=(
                Money(command.min_order_amount) if command.min_order_amount else None
            ),
            target_user_id=command.target_user_id,
            stacks_with_campaign=command.stacks_with_campaign,
            first_purchase_only=command.first_purchase_only,
            state=PublicationState.PUBLISHED,
            created_by=actor_id,
        )

    async def _require_campaign(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._campaigns.get(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found.", campaign_id=str(campaign_id))
        return campaign

    async def _record(
        self,
        action: CatalogAuditAction,
        target_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        **metadata: Any,
    ) -> None:
        await self._audit.record(
            action,
            actor_id=actor_id,
            target_type="catalog",
            target_id=str(target_id),
            **metadata,
        )
