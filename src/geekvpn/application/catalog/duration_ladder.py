"""Generate a whole duration ladder for a product from one monthly price.

This closes the gap between `domain/catalog/durations.py`, which decides what
the rungs *are*, and `CatalogAdminService.create_plan`, which only ever made
one package at a time.

Why this exists as a service rather than a loop in the admin panel: the
ladder has rules that must not drift between products. Quota scales with the
term, the compare-at price has to be the honest un-discounted figure, and the
sort order has to follow the term length or the storefront renders the
annual plan above the monthly one. Encoding that once means a new product is
correct by construction instead of correct if the operator was careful.

Generated plans land in DRAFT. Publishing is a separate, deliberate step -
nobody should be able to put four new packages on sale with one click and no
review.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from geekvpn.application.catalog.catalog_admin import CatalogAdminService
from geekvpn.application.catalog.commands import CreatePlanCommand
from geekvpn.domain.catalog.durations import (
    DEFAULT_LADDER,
    DurationRung,
)
from geekvpn.domain.catalog.enums import PlanType
from geekvpn.domain.catalog.errors import CatalogError
from geekvpn.domain.catalog.plan import Plan


@dataclass(frozen=True, slots=True)
class LadderRequest:
    product_id: uuid.UUID
    #: Price of the 30-day package. Every other rung is derived from it.
    monthly_price: int
    plan_type: PlanType
    #: Slug prefix; each plan becomes ``<prefix>-<rung slug>``.
    slug_prefix: str
    #: Human name prefix, e.g. "\u062a\u0631\u0628\u0648". The rung's own Persian name is
    #: appended, giving "\u062a\u0631\u0628\u0648 \u0633\u0647\u200c\u0645\u0627\u0647\u0647".
    name_prefix_fa: str
    #: Volume of the 30-day package, in GiB. Scaled up with the term for
    #: TRAFFIC plans, ignored for the others.
    monthly_quota_gib: int | None = None
    #: Fair-use ceiling for DURATION plans. Constant across terms, because a
    #: daily limit that grew with the term would defeat its purpose.
    daily_quota_gib: int | None = None
    device_limit: int = 1
    cashback_bps: int = 0


class DurationLadderService:
    def __init__(self, admin: CatalogAdminService) -> None:
        self._admin = admin

    async def generate(
        self,
        request: LadderRequest,
        *,
        rungs: tuple[DurationRung, ...] = DEFAULT_LADDER,
        actor_id: uuid.UUID | None = None,
    ) -> list[Plan]:
        self._validate(request, rungs)

        created: list[Plan] = []
        for index, rung in enumerate(rungs):
            command = CreatePlanCommand(
                product_id=request.product_id,
                slug=f"{request.slug_prefix}-{rung.slug}",
                plan_type=request.plan_type,
                name_fa=f"{request.name_prefix_fa} {rung.name_fa}".strip(),
                duration_days=rung.days,
                base_price=rung.price_from_monthly(request.monthly_price),
                quota_gib=self._quota_for(request, rung),
                daily_quota_gib=(
                    request.daily_quota_gib if request.plan_type is PlanType.DURATION else None
                ),
                device_limit=request.device_limit + rung.bonus_devices,
                badge_fa=rung.badge_fa,
                compare_at_price=self._compare_at_for(request, rung),
                cashback_bps=request.cashback_bps,
                # Shortest first, matching LADDER order, so the storefront
                # reads as a ladder rather than an arbitrary pile.
                sort_order=index * 10,
                is_featured=rung.badge_fa is not None,
            )
            created.append(await self._admin.create_plan(command, actor_id=actor_id))
        return created

    # -- internals ---------------------------------------------------------

    def _quota_for(self, request: LadderRequest, rung: DurationRung) -> int | None:
        """Scale the volume with the term.

        A 90-day package that carried the same 50GB as the 30-day one would be
        a worse deal per month, which is the opposite of what the discount
        curve promises.
        """
        if request.plan_type is not PlanType.TRAFFIC:
            return None
        if request.monthly_quota_gib is None:
            return None
        return int(request.monthly_quota_gib * rung.days / 30)

    def _compare_at_for(self, request: LadderRequest, rung: DurationRung) -> int | None:
        """The struck-through price: what this term would cost at the monthly
        rate.

        Only set where it is truthful. On the baseline there is nothing to
        compare against, and on the weekly rung the "before" price is *lower*
        than the real one - showing it would be a fake discount.
        """
        if rung.discount_bps <= 0:
            return None
        return int(request.monthly_price * rung.days / 30)

    def _validate(self, request: LadderRequest, rungs: tuple[DurationRung, ...]) -> None:
        if not rungs:
            raise CatalogError("A ladder needs at least one duration.")
        if request.monthly_price <= 0:
            raise CatalogError("The monthly price must be positive.")
        if len({rung.days for rung in rungs}) != len(rungs):
            raise CatalogError("The ladder contains duplicate durations.")
        if request.plan_type is PlanType.TRAFFIC and not request.monthly_quota_gib:
            raise CatalogError("A traffic ladder needs a monthly volume.")
        if request.plan_type is PlanType.DURATION and not request.daily_quota_gib:
            raise CatalogError("A duration ladder needs a daily fair-use limit.")
