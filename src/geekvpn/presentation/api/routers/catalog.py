"""Customer-facing storefront and quoting.

Every response here is priced for the caller. There is no anonymous price list,
because loyalty tier and first-purchase status both move the number, and
showing a price the customer will not actually be charged is worse than showing
no price at all.

The storefront is one call. The Mini App renders tabs, cards, badges, countdown
timers and strike-through prices from a single payload, because on a mobile
connection in Iran a second round trip is the difference between instant and
sluggish.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from geekvpn.application.catalog.dto import QuoteView
from geekvpn.domain.catalog.rewards import LoyaltyTier
from geekvpn.presentation.api.schemas_catalog import (
    CouponPreviewRequest,
    CouponPreviewResponse,
    QuoteResponse,
    StorefrontResponse,
)
from geekvpn.presentation.api.security import CurrentUser, ScopeDep

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get(
    "/storefront",
    response_model=StorefrontResponse,
    summary="The whole shoppable catalogue, priced for this customer",
)
async def storefront(subject: CurrentUser, scope: ScopeDep) -> StorefrontResponse:
    view = await scope.storefront.load(
        user_id=subject.subject_id,
        loyalty_tier=await _tier_for(scope, subject.subject_id),
        is_first_purchase=await _is_first_purchase(scope, subject.subject_id),
    )
    return StorefrontResponse.model_validate(view)


@router.get(
    "/plans/{plan_id}/quote",
    response_model=QuoteResponse,
    summary="Price one package, optionally with a coupon",
)
async def quote_plan(
    plan_id: uuid.UUID,
    subject: CurrentUser,
    scope: ScopeDep,
    coupon: str | None = Query(default=None, max_length=32),
) -> QuoteResponse:
    """The authoritative price.

    The order flow calls this again immediately before charging and compares
    the total, so a flash sale that ends between "view" and "pay" is caught
    rather than honoured indefinitely.
    """
    quote = await scope.quoting.quote(
        plan_id=plan_id,
        user_id=subject.subject_id,
        coupon_code=coupon,
        loyalty_tier=await _tier_for(scope, subject.subject_id),
        is_first_purchase=await _is_first_purchase(scope, subject.subject_id),
    )
    return QuoteResponse.model_validate(QuoteView.of(quote))


@router.post(
    "/coupons/preview",
    response_model=CouponPreviewResponse,
    summary="Try a discount code without committing to a purchase",
)
async def preview_coupon(
    payload: CouponPreviewRequest, subject: CurrentUser, scope: ScopeDep
) -> CouponPreviewResponse:
    """A rejected code is a 200 with `is_valid: false`, not an error.

    The bot calls this while the customer is still typing. Turning "that code
    expired" into an HTTP 4xx would force every client to catch, classify and
    re-translate a message the server already wrote in Persian.
    """
    preview = await scope.quoting.preview_coupon(
        plan_id=payload.plan_id,
        code=payload.code,
        user_id=subject.subject_id,
        loyalty_tier=await _tier_for(scope, subject.subject_id),
        is_first_purchase=await _is_first_purchase(scope, subject.subject_id),
    )
    return CouponPreviewResponse(
        code=preview.code,
        is_valid=preview.is_valid,
        discount=preview.discount,
        total_after=preview.total_after,
        message=preview.message_fa,
    )


# -- placeholders resolved in Phase 5 --------------------------------------
#
# Loyalty tier derives from lifetime spend and first-purchase status from the
# order count. Both tables land with the order engine. Until then every
# customer prices as Bronze, which is the conservative direction: nobody is
# accidentally given a discount they have not earned.


async def _tier_for(scope: object, user_id: uuid.UUID) -> LoyaltyTier:
    return LoyaltyTier.BRONZE


async def _is_first_purchase(scope: object, user_id: uuid.UUID) -> bool:
    return False
