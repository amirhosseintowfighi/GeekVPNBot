"""Admin configuration for the entire product engine.

Every knob the brief asked to be "configurable from Admin Panel" is reachable
here: categories, products, the three plan types, prices, cashback rates,
coupons, campaigns and flash sales. Nothing about the catalogue requires a
deploy or a SQL console.

Two conventions carried over from Phase 2:

* Permissions are declared on the route, not checked in the handler, so the
  guard is visible in the OpenAPI document and cannot be forgotten inside a
  branch.
* Nothing is deleted. Everything is archived. A plan referenced by a historical
  order must stay readable or the invoice becomes unexplainable.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from geekvpn.application.catalog.commands import (
    UNSET,
    CreateCampaignCommand,
    CreateCategoryCommand,
    CreateCouponCommand,
    CreatePlanCommand,
    CreateProductCommand,
    ScopeCommand,
    UpdateCategoryCommand,
    UpdatePlanCommand,
    UpdateProductCommand,
)
from geekvpn.application.catalog.dto import QuoteView
from geekvpn.domain.catalog.campaign import Campaign
from geekvpn.domain.catalog.category import Category
from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.catalog.rewards import LoyaltyTier
from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.api.schemas_catalog import (
    AdminQuoteRequest,
    CampaignAdminResponse,
    CampaignCreateRequest,
    CampaignPerformanceResponse,
    CampaignStateRequest,
    CategoryAdminResponse,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CouponAdminResponse,
    CouponBulkCreateRequest,
    CouponCreateRequest,
    PlanAdminResponse,
    PlanCreateRequest,
    PlanUpdateRequest,
    ProductAdminResponse,
    ProductCreateRequest,
    ProductPanelBindRequest,
    ProductUpdateRequest,
    PublishRequest,
    QuoteResponse,
    ScopeRequest,
)
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep, requires

router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])

READ = Depends(requires(Permission.PACKAGES_READ))
WRITE = Depends(requires(Permission.PACKAGES_WRITE))
PROMOTE = Depends(requires(Permission.CAMPAIGNS_WRITE))


def _scope(payload: ScopeRequest) -> ScopeCommand:
    return ScopeCommand(
        plan_ids=tuple(payload.plan_ids),
        product_ids=tuple(payload.product_ids),
        tiers=tuple(payload.tiers),
    )


# -- categories ------------------------------------------------------------


def _category_view(category: Category) -> CategoryAdminResponse:
    return CategoryAdminResponse(
        id=category.id,
        slug=category.slug,
        name_fa=category.name_fa,
        name_en=category.name_en,
        description_fa=category.description_fa,
        icon=category.icon,
        sort_order=category.sort_order,
        state=category.state.value,
    )


@router.get(
    "/categories",
    response_model=list[CategoryAdminResponse],
    dependencies=[READ],
    summary="List every category, including drafts and archived ones",
)
async def list_categories(scope: ScopeDep) -> list[CategoryAdminResponse]:
    return [_category_view(c) for c in await scope.catalog_admin.list_categories()]


@router.post(
    "/categories",
    response_model=CategoryAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE],
    summary="Create a category",
)
async def create_category(
    payload: CategoryCreateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> CategoryAdminResponse:
    category = await scope.catalog_admin.create_category(
        CreateCategoryCommand(**payload.model_dump()), actor_id=actor.subject_id
    )
    return _category_view(category)


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryAdminResponse,
    dependencies=[WRITE],
    summary="Update a category",
)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdateRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> CategoryAdminResponse:
    category = await scope.catalog_admin.update_category(
        category_id,
        UpdateCategoryCommand(**payload.model_dump()),
        actor_id=actor.subject_id,
    )
    return _category_view(category)


@router.put(
    "/categories/{category_id}/state",
    response_model=CategoryAdminResponse,
    dependencies=[WRITE],
    summary="Publish or archive a category",
)
async def set_category_state(
    category_id: uuid.UUID,
    payload: PublishRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> CategoryAdminResponse:
    category = await scope.catalog_admin.set_category_state(
        category_id, publish=payload.publish, actor_id=actor.subject_id
    )
    return _category_view(category)


# -- products --------------------------------------------------------------


def _product_view(product: Product) -> ProductAdminResponse:
    return ProductAdminResponse(
        id=product.id,
        category_id=product.category_id,
        slug=product.slug,
        tier=product.tier.value,
        name_fa=product.name_fa,
        tagline_fa=product.tagline_fa,
        description_fa=product.description_fa,
        features_fa=list(product.features_fa),
        icon=product.icon,
        badge_fa=product.badge_fa,
        accent_color=product.accent_color,
        sort_order=product.sort_order,
        is_featured=product.is_featured,
        state=product.state.value,
        panel_id=product.panel_id,
        node_tags=list(product.node_tags),
        is_provisionable=product.is_provisionable,
    )


@router.get(
    "/products",
    response_model=list[ProductAdminResponse],
    dependencies=[READ],
    summary="List products",
)
async def list_products(
    scope: ScopeDep, category_id: uuid.UUID | None = Query(default=None)
) -> list[ProductAdminResponse]:
    products = await scope.catalog_admin.list_products(category_id=category_id)
    return [_product_view(p) for p in products]


@router.post(
    "/products",
    response_model=ProductAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE],
    summary="Create a product tier",
)
async def create_product(
    payload: ProductCreateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> ProductAdminResponse:
    data = payload.model_dump()
    data["features_fa"] = tuple(data["features_fa"])
    data["node_tags"] = tuple(data["node_tags"])
    product = await scope.catalog_admin.create_product(
        CreateProductCommand(**data), actor_id=actor.subject_id
    )
    return _product_view(product)


@router.patch(
    "/products/{product_id}",
    response_model=ProductAdminResponse,
    dependencies=[WRITE],
    summary="Update a product",
)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdateRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> ProductAdminResponse:
    data = payload.model_dump()
    if data.get("features_fa") is not None:
        data["features_fa"] = tuple(data["features_fa"])
    product = await scope.catalog_admin.update_product(
        product_id, UpdateProductCommand(**data), actor_id=actor.subject_id
    )
    return _product_view(product)


@router.put(
    "/products/{product_id}/panel",
    response_model=ProductAdminResponse,
    dependencies=[WRITE],
    summary="Bind a product to the VPN panel that will provision it",
)
async def bind_panel(
    product_id: uuid.UUID,
    payload: ProductPanelBindRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> ProductAdminResponse:
    product = await scope.catalog_admin.bind_product_panel(
        product_id,
        panel_id=payload.panel_id,
        node_tags=tuple(payload.node_tags),
        actor_id=actor.subject_id,
    )
    return _product_view(product)


@router.put(
    "/products/{product_id}/state",
    response_model=ProductAdminResponse,
    dependencies=[WRITE],
    summary="Publish or archive a product",
)
async def set_product_state(
    product_id: uuid.UUID,
    payload: PublishRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> ProductAdminResponse:
    """Publishing fails with 409 if no panel is bound.

    That refusal is deliberate. Selling something provisioning cannot deliver
    is the most expensive mistake this platform can make.
    """
    product = await scope.catalog_admin.set_product_state(
        product_id, publish=payload.publish, actor_id=actor.subject_id
    )
    return _product_view(product)


# -- plans -----------------------------------------------------------------


def _plan_view(plan: Plan) -> PlanAdminResponse:
    price_per_gib = plan.price_per_gib
    return PlanAdminResponse(
        id=plan.id,
        product_id=plan.product_id,
        slug=plan.slug,
        plan_type=plan.plan_type.value,
        name_fa=plan.name_fa,
        description_fa=plan.description_fa,
        badge_fa=plan.badge_fa,
        duration_days=plan.duration_days,
        quota_gib=plan.quota_gib,
        daily_quota_gib=plan.daily_quota_gib,
        device_limit=plan.device_limit,
        base_price=plan.base_price.amount,
        compare_at_price=(plan.compare_at_price.amount if plan.compare_at_price else None),
        min_price=plan.min_price.amount,
        cashback_bps=plan.cashback_bps,
        max_per_user=plan.max_per_user,
        sort_order=plan.sort_order,
        is_featured=plan.is_featured,
        state=plan.state.value,
        price_per_gib=price_per_gib,
        savings_percent=plan.savings_bps // 100,
    )


@router.get(
    "/plans",
    response_model=list[PlanAdminResponse],
    dependencies=[READ],
    summary="List packages",
)
async def list_plans(
    scope: ScopeDep, product_id: uuid.UUID | None = Query(default=None)
) -> list[PlanAdminResponse]:
    return [_plan_view(p) for p in await scope.catalog_admin.list_plans(product_id=product_id)]


@router.post(
    "/plans",
    response_model=PlanAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE],
    summary="Create a ready-made package",
)
async def create_plan(
    payload: PlanCreateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> PlanAdminResponse:
    """Define one purchasable package.

    Packages are bought whole. There is no mid-cycle traffic top-up anywhere in
    this API, by design: the customer picks a package and buys it, which is the
    simplest possible purchase. Offering more traffic means defining a bigger
    package here.
    """
    plan = await scope.catalog_admin.create_plan(
        CreatePlanCommand(**payload.model_dump()), actor_id=actor.subject_id
    )
    return _plan_view(plan)


@router.patch(
    "/plans/{plan_id}",
    response_model=PlanAdminResponse,
    dependencies=[WRITE],
    summary="Update a package",
)
async def update_plan(
    plan_id: uuid.UUID,
    payload: PlanUpdateRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> PlanAdminResponse:
    data = payload.model_dump()
    clear = data.pop("clear_compare_at_price", False)
    command = UpdatePlanCommand(
        **{k: v for k, v in data.items() if k != "compare_at_price"},
        compare_at_price=(None if clear else (data["compare_at_price"] or UNSET)),
    )
    plan = await scope.catalog_admin.update_plan(plan_id, command, actor_id=actor.subject_id)
    return _plan_view(plan)


@router.put(
    "/plans/{plan_id}/state",
    response_model=PlanAdminResponse,
    dependencies=[WRITE],
    summary="Publish or archive a package",
)
async def set_plan_state(
    plan_id: uuid.UUID,
    payload: PublishRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> PlanAdminResponse:
    plan = await scope.catalog_admin.set_plan_state(
        plan_id, publish=payload.publish, actor_id=actor.subject_id
    )
    return _plan_view(plan)


@router.post(
    "/plans/quote",
    response_model=QuoteResponse,
    dependencies=[READ],
    summary="Preview exactly what a customer would be charged",
)
async def preview_quote(payload: AdminQuoteRequest, scope: ScopeDep) -> QuoteResponse:
    """Price an unpublished package before pressing publish.

    `enforce_purchasable=False` is what makes this useful: an operator can see
    the final number, including campaigns and rounding, while the plan is still
    a draft.
    """
    quote = await scope.quoting.quote(
        plan_id=payload.plan_id,
        coupon_code=payload.coupon_code,
        loyalty_tier=LoyaltyTier(payload.loyalty_tier),
        is_first_purchase=payload.is_first_purchase,
        enforce_purchasable=False,
    )
    return QuoteResponse.model_validate(QuoteView.of(quote))


# -- coupons ---------------------------------------------------------------


def _coupon_view(coupon: Coupon) -> CouponAdminResponse:
    return CouponAdminResponse(
        id=coupon.id,
        code=coupon.code,
        kind=coupon.kind.value,
        description_fa=coupon.description_fa,
        discount_label=coupon.discount.label,
        starts_at=coupon.window.starts_at,
        ends_at=coupon.window.ends_at,
        max_redemptions=coupon.max_redemptions,
        max_per_user=coupon.max_per_user,
        redemption_count=coupon.redemption_count,
        remaining_redemptions=coupon.remaining_redemptions,
        min_order_amount=coupon.min_order_amount.amount,
        target_user_id=coupon.target_user_id,
        stacks_with_campaign=coupon.stacks_with_campaign,
        first_purchase_only=coupon.first_purchase_only,
        state=coupon.state.value,
    )


def _coupon_command(payload: CouponCreateRequest) -> CreateCouponCommand:
    data = payload.model_dump()
    data["scope"] = _scope(payload.scope)
    return CreateCouponCommand(**data)


@router.get(
    "/coupons",
    response_model=list[CouponAdminResponse],
    dependencies=[READ],
    summary="List discount codes",
)
async def list_coupons(
    scope: ScopeDep,
    active_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CouponAdminResponse]:
    coupons = await scope.promotions.list_coupons(
        active_only=active_only, limit=limit, offset=offset
    )
    return [_coupon_view(c) for c in coupons]


@router.post(
    "/coupons",
    response_model=CouponAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[PROMOTE],
    summary="Create a discount code",
)
async def create_coupon(
    payload: CouponCreateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> CouponAdminResponse:
    coupon = await scope.promotions.create_coupon(
        _coupon_command(payload), actor_id=actor.subject_id
    )
    return _coupon_view(coupon)


@router.post(
    "/coupons/bulk",
    response_model=list[CouponAdminResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[PROMOTE],
    summary="Generate a batch of single-use codes",
)
async def bulk_create_coupons(
    payload: CouponBulkCreateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> list[CouponAdminResponse]:
    coupons = await scope.promotions.bulk_create_coupons(
        _coupon_command(payload.template),
        count=payload.count,
        prefix=payload.prefix,
        actor_id=actor.subject_id,
    )
    return [_coupon_view(c) for c in coupons]


@router.delete(
    "/coupons/{coupon_id}",
    response_model=CouponAdminResponse,
    dependencies=[PROMOTE],
    summary="Archive a discount code",
)
async def archive_coupon(
    coupon_id: uuid.UUID, actor: CurrentAdmin, scope: ScopeDep
) -> CouponAdminResponse:
    """Archives rather than deletes.

    A redeemed coupon is referenced by an order; removing the row would turn a
    historical invoice into an unexplainable discount.
    """
    coupon = await scope.promotions.archive_coupon(coupon_id, actor_id=actor.subject_id)
    return _coupon_view(coupon)


# -- campaigns and flash sales ---------------------------------------------


def _campaign_view(campaign: Campaign) -> CampaignAdminResponse:
    return CampaignAdminResponse(
        id=campaign.id,
        slug=campaign.slug,
        kind=campaign.kind.value,
        name_fa=campaign.name_fa,
        description_fa=campaign.description_fa,
        banner_url=campaign.banner_url,
        discount_label=campaign.discount.label,
        starts_at=campaign.window.starts_at,
        ends_at=campaign.window.ends_at,
        max_redemptions=campaign.max_redemptions,
        redemption_count=campaign.redemption_count,
        remaining_stock=campaign.remaining_stock,
        priority=campaign.priority,
        state=campaign.state.value,
    )


@router.get(
    "/campaigns",
    response_model=list[CampaignAdminResponse],
    dependencies=[READ],
    summary="List campaigns and flash sales",
)
async def list_campaigns(
    scope: ScopeDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CampaignAdminResponse]:
    campaigns = await scope.promotions.list_campaigns(limit=limit, offset=offset)
    return [_campaign_view(c) for c in campaigns]


@router.post(
    "/campaigns",
    response_model=CampaignAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[PROMOTE],
    summary="Create a campaign or flash sale",
)
async def create_campaign(
    payload: CampaignCreateRequest, actor: CurrentAdmin, scope: ScopeDep
) -> CampaignAdminResponse:
    """A flash sale is a campaign with an end time, and the end time is
    mandatory for that kind - both here and in the database."""
    data = payload.model_dump()
    data["scope"] = _scope(payload.scope)
    campaign = await scope.promotions.create_campaign(
        CreateCampaignCommand(**data), actor_id=actor.subject_id
    )
    return _campaign_view(campaign)


@router.put(
    "/campaigns/{campaign_id}/state",
    response_model=CampaignAdminResponse,
    dependencies=[PROMOTE],
    summary="Activate, pause or archive a campaign",
)
async def set_campaign_state(
    campaign_id: uuid.UUID,
    payload: CampaignStateRequest,
    actor: CurrentAdmin,
    scope: ScopeDep,
) -> CampaignAdminResponse:
    campaign = await scope.promotions.set_campaign_state(
        campaign_id, state=payload.state, actor_id=actor.subject_id
    )
    return _campaign_view(campaign)


@router.get(
    "/campaigns/{campaign_id}/performance",
    response_model=CampaignPerformanceResponse,
    dependencies=[READ],
    summary="Live campaign counters",
)
async def campaign_performance(
    campaign_id: uuid.UUID, scope: ScopeDep
) -> CampaignPerformanceResponse:
    data = await scope.promotions.campaign_performance(campaign_id)
    return CampaignPerformanceResponse.model_validate(data)
