"""Admin CRUD over categories, products and plans.

Every mutating method writes an audit entry. The catalogue is where money is
defined, so "who changed this, when, and from what" is not optional.

Deletion is not offered. Anything that has been sold is historical financial
record; archiving hides it from the storefront while keeping every past invoice
meaningful.
"""

from __future__ import annotations

import uuid
from typing import Any

from geekvpn.application.catalog.commands import (
    UNSET,
    CreateCategoryCommand,
    CreatePlanCommand,
    CreateProductCommand,
    UpdateCategoryCommand,
    UpdatePlanCommand,
    UpdateProductCommand,
)
from geekvpn.application.ports.catalog import (
    CategoryRepository,
    PlanRepository,
    ProductRepository,
)
from geekvpn.application.ports.catalog_audit import CatalogAuditRecorder
from geekvpn.application.ports.clock import Clock
from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.catalog.audit import CatalogAuditAction
from geekvpn.domain.catalog.category import Category
from geekvpn.domain.catalog.enums import PublicationState
from geekvpn.domain.catalog.errors import CatalogConflict, CatalogError
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product


class CatalogAdminService:
    def __init__(
        self,
        *,
        categories: CategoryRepository,
        products: ProductRepository,
        plans: PlanRepository,
        clock: Clock,
        audit: CatalogAuditRecorder,
    ) -> None:
        self._categories = categories
        self._products = products
        self._plans = plans
        self._clock = clock
        self._audit = audit

    # -- categories --------------------------------------------------------

    async def list_categories(self) -> list[Category]:
        return list(await self._categories.list_all())

    async def create_category(
        self, command: CreateCategoryCommand, *, actor_id: uuid.UUID | None = None
    ) -> Category:
        if await self._categories.get_by_slug(command.slug) is not None:
            raise CatalogConflict("A category with this slug already exists.", slug=command.slug)
        category = Category(
            category_id=uuid.uuid4(),
            slug=command.slug,
            name_fa=command.name_fa,
            name_en=command.name_en,
            description_fa=command.description_fa,
            icon=command.icon,
            sort_order=command.sort_order,
        )
        await self._categories.add(category)
        await self._record(
            CatalogAuditAction.CATEGORY_CREATED, category.id, actor_id, slug=category.slug
        )
        return category

    async def update_category(
        self,
        category_id: uuid.UUID,
        command: UpdateCategoryCommand,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Category:
        category = await self._require_category(category_id)
        changed = _apply(
            category,
            name_fa=command.name_fa,
            name_en=command.name_en,
            description_fa=command.description_fa,
            icon=command.icon,
            sort_order=command.sort_order,
        )
        await self._categories.update(category)
        await self._record(
            CatalogAuditAction.CATEGORY_UPDATED,
            category.id,
            actor_id,
            fields=sorted(changed),
        )
        return category

    async def set_category_state(
        self,
        category_id: uuid.UUID,
        *,
        state: PublicationState,
        actor_id: uuid.UUID | None = None,
    ) -> Category:
        category = await self._require_category(category_id)
        if state is PublicationState.PUBLISHED:
            category.publish()
        elif state is PublicationState.ARCHIVED:
            category.archive()
        else:
            category.state = state
        await self._categories.update(category)
        await self._record(
            CatalogAuditAction.CATEGORY_STATE_CHANGED,
            category.id,
            actor_id,
            state=state.value,
        )
        return category

    # -- products ----------------------------------------------------------

    async def list_products(self, *, category_id: uuid.UUID | None = None) -> list[Product]:
        return list(await self._products.list_all(category_id=category_id))

    async def create_product(
        self, command: CreateProductCommand, *, actor_id: uuid.UUID | None = None
    ) -> Product:
        if await self._products.get_by_slug(command.slug) is not None:
            raise CatalogConflict("A product with this slug already exists.", slug=command.slug)
        await self._require_category(command.category_id)

        product = Product(
            product_id=uuid.uuid4(),
            category_id=command.category_id,
            slug=command.slug,
            tier=command.tier,
            name_fa=command.name_fa,
            tagline_fa=command.tagline_fa,
            description_fa=command.description_fa,
            features_fa=command.features_fa,
            icon=command.icon,
            badge_fa=command.badge_fa,
            accent_color=command.accent_color,
            sort_order=command.sort_order,
            panel_id=command.panel_id,
            node_tags=command.node_tags,
            is_featured=command.is_featured,
        )
        await self._products.add(product)
        await self._record(
            CatalogAuditAction.PRODUCT_CREATED,
            product.id,
            actor_id,
            slug=product.slug,
            tier=product.tier.value,
        )
        return product

    async def update_product(
        self,
        product_id: uuid.UUID,
        command: UpdateProductCommand,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Product:
        product = await self._require_product(product_id)
        changed = _apply(
            product,
            name_fa=command.name_fa,
            tagline_fa=command.tagline_fa,
            description_fa=command.description_fa,
            icon=command.icon,
            badge_fa=command.badge_fa,
            accent_color=command.accent_color,
            sort_order=command.sort_order,
            is_featured=command.is_featured,
        )
        if command.features_fa is not None:
            product.update_features(command.features_fa)
            changed.add("features_fa")
        await self._products.update(product)
        await self._record(
            CatalogAuditAction.PRODUCT_UPDATED,
            product.id,
            actor_id,
            fields=sorted(changed),
        )
        return product

    async def bind_product_panel(
        self,
        product_id: uuid.UUID,
        *,
        panel_id: uuid.UUID,
        node_tags: tuple[str, ...] = (),
        actor_id: uuid.UUID | None = None,
    ) -> Product:
        product = await self._require_product(product_id)
        product.bind_panel(panel_id, node_tags=node_tags)
        await self._products.update(product)
        await self._record(
            CatalogAuditAction.PRODUCT_PANEL_BOUND,
            product.id,
            actor_id,
            panel_id=str(panel_id),
            node_tags=list(node_tags),
        )
        return product

    async def set_product_state(
        self,
        product_id: uuid.UUID,
        *,
        state: PublicationState,
        actor_id: uuid.UUID | None = None,
    ) -> Product:
        product = await self._require_product(product_id)
        if state is PublicationState.PUBLISHED:
            # Raises if no panel is bound. See Product.publish().
            product.publish()
            action = CatalogAuditAction.PRODUCT_PUBLISHED
        elif state is PublicationState.ARCHIVED:
            product.archive()
            action = CatalogAuditAction.PRODUCT_ARCHIVED
        else:
            product.state = state
            action = CatalogAuditAction.PRODUCT_UPDATED
        await self._products.update(product)
        await self._record(action, product.id, actor_id, state=state.value)
        return product

    # -- plans -------------------------------------------------------------

    async def list_plans(self, *, product_id: uuid.UUID | None = None) -> list[Plan]:
        plans = (
            await self._plans.list_all()
            if product_id is None
            else await self._plans.list_for_product(product_id)
        )
        return list(plans)

    async def create_plan(
        self, command: CreatePlanCommand, *, actor_id: uuid.UUID | None = None
    ) -> Plan:
        """Create one ready-made package.

        Note the absence of any add-on or top-up concept: a package is a fixed
        volume for a fixed duration at a fixed price. Wanting more means buying
        the next package up.
        """
        if await self._plans.get_by_slug(command.slug) is not None:
            raise CatalogConflict("A plan with this slug already exists.", slug=command.slug)
        await self._require_product(command.product_id)

        plan = Plan(
            plan_id=uuid.uuid4(),
            product_id=command.product_id,
            slug=command.slug,
            plan_type=command.plan_type,
            name_fa=command.name_fa,
            duration_days=command.duration_days,
            base_price=Money(command.base_price),
            quota_gib=command.quota_gib,
            daily_quota_gib=command.daily_quota_gib,
            description_fa=command.description_fa,
            badge_fa=command.badge_fa,
            device_limit=command.device_limit,
            compare_at_price=(
                Money(command.compare_at_price)
                if isinstance(command.compare_at_price, int)
                else None
            ),
            min_price=None if command.min_price is None else Money(command.min_price),
            cashback_bps=command.cashback_bps,
            max_per_user=command.max_per_user,
            sort_order=command.sort_order,
            is_featured=command.is_featured,
        )
        await self._plans.add(plan)
        await self._record(
            CatalogAuditAction.PLAN_CREATED,
            plan.id,
            actor_id,
            slug=plan.slug,
            base_price=plan.base_price.amount,
        )
        return plan

    async def update_plan(
        self,
        plan_id: uuid.UUID,
        command: UpdatePlanCommand,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Plan:
        plan = await self._require_plan(plan_id)

        # Price changes go through the aggregate so the event is emitted and
        # the price-invariant check runs.
        new_price = None if command.base_price is None else Money(command.base_price)
        if new_price is not None and new_price != plan.base_price:
            old = plan.base_price
            plan.change_price(new_price, changed_by=actor_id)
            await self._record(
                CatalogAuditAction.PLAN_PRICE_CHANGED,
                plan.id,
                actor_id,
                old_price=old.amount,
                new_price=plan.base_price.amount,
            )

        changed = _apply(
            plan,
            name_fa=command.name_fa,
            description_fa=command.description_fa,
            badge_fa=command.badge_fa,
            duration_days=command.duration_days,
            quota_gib=command.quota_gib,
            daily_quota_gib=command.daily_quota_gib,
            device_limit=command.device_limit,
            compare_at_price=(
                Money(command.compare_at_price)
                if isinstance(command.compare_at_price, int)
                else None
            ),
            min_price=None if command.min_price is None else Money(command.min_price),
            cashback_bps=command.cashback_bps,
            max_per_user=command.max_per_user,
            sort_order=command.sort_order,
            is_featured=command.is_featured,
        )

        # Attributes were assigned directly, bypassing __init__. Without this
        # an unlimited plan could be given a volume cap and persisted.
        plan.revalidate()

        await self._plans.update(plan)
        await self._record(
            CatalogAuditAction.PLAN_UPDATED, plan.id, actor_id, fields=sorted(changed)
        )
        return plan

    async def set_plan_state(
        self,
        plan_id: uuid.UUID,
        *,
        state: PublicationState,
        actor_id: uuid.UUID | None = None,
    ) -> Plan:
        plan = await self._require_plan(plan_id)

        if state is PublicationState.PUBLISHED:
            product = await self._require_product(plan.product_id)
            if not product.is_visible:
                # A published plan under a draft product is reachable by direct
                # link but invisible in the shop - the worst of both.
                raise CatalogError(
                    "Publish the product before publishing its packages.",
                    plan_id=str(plan.id),
                    product_id=str(product.id),
                )
            plan.publish()
            action = CatalogAuditAction.PLAN_PUBLISHED
        elif state is PublicationState.ARCHIVED:
            plan.archive()
            action = CatalogAuditAction.PLAN_ARCHIVED
        else:
            plan.state = state
            action = CatalogAuditAction.PLAN_UPDATED

        await self._plans.update(plan)
        await self._record(action, plan.id, actor_id, state=state.value)
        return plan

    # -- internals ---------------------------------------------------------

    async def _require_category(self, category_id: uuid.UUID) -> Category:
        category = await self._categories.get(category_id)
        if category is None:
            raise NotFoundError("Category not found.", category_id=str(category_id))
        return category

    async def _require_product(self, product_id: uuid.UUID) -> Product:
        product = await self._products.get(product_id)
        if product is None:
            raise NotFoundError("Product not found.", product_id=str(product_id))
        return product

    async def _require_plan(self, plan_id: uuid.UUID) -> Plan:
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise NotFoundError("Plan not found.", plan_id=str(plan_id))
        return plan

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


def _apply(entity: Any, **fields: Any) -> set[str]:
    """Assign provided fields, returning the names that actually changed.

    `None` means "leave unchanged"; `UNSET` also means unchanged but is used
    for fields where `None` is a meaningful value to assign. Returning the
    changed set is what lets the audit entry record precisely which fields an
    operator touched rather than "updated".
    """
    changed: set[str] = set()
    for name, value in fields.items():
        if value is None or value is UNSET:
            continue
        if getattr(entity, name, None) != value:
            setattr(entity, name, value)
            changed.add(name)
    return changed
