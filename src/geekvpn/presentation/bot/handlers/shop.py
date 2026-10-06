"""Storefront browsing: categories -> products -> packages.

The storefront is loaded fresh on every screen rather than cached in FSM
state. It is a single batched read by design (see `StorefrontService`), and
caching it would mean a customer could tap through to a package whose flash
sale ended two screens ago -- then see a different price at checkout. Loading
live is the cheaper mistake.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from geekvpn.application.bot.services import BotServices
from geekvpn.application.catalog.dto import CategoryView, ProductView, StorefrontView
from geekvpn.application.platform.settings_service import SHOW_CAPACITY
from geekvpn.application.provisioning import panel_id_for
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import (
    answer,
    brand_of,
    match_ref,
    safe_edit,
    short_ref,
    tier_of,
    toast,
)
from geekvpn.presentation.bot.states import Purchase
from geekvpn.presentation.bot.ui import emoji as E
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, ShopCB
from geekvpn.presentation.bot.ui.fa import fa_digits

logger = get_logger("bot.shop")

router = Router(name="shop")


async def load_storefront(*, user: Any, scope: Any, services: BotServices) -> StorefrontView:
    """Load the catalogue priced for this specific customer.

    Loyalty tier drives cashback and some campaign scopes, so it is resolved
    from lifetime spend before pricing rather than defaulting to bronze.
    """
    try:
        snapshot = await services.wallet.snapshot(user.id)
    except Exception:
        from geekvpn.application.bot.read_models import WalletSnapshot

        snapshot = WalletSnapshot()

    try:
        profile = await services.profiles.summary(user.id)
        is_first = profile.order_count == 0
    except Exception:
        is_first = False

    view: StorefrontView = await scope.storefront.load(
        user_id=user.id,
        loyalty_tier=tier_of(snapshot.lifetime_spend),
        is_first_purchase=is_first,
        wallet_balance=snapshot.balance,
        # A reseller's storefront shows a reseller's prices. Empty in the
        # platform's own bot, where `reseller` is None.
        # Read off the scope rather than taken as an argument: this is called
        # from seven places, and one that forgot would quietly show a
        # reseller's customer our prices.
        retail_prices=(
            scope.reseller.retail_overrides if scope.reseller is not None else None
        ),
    )
    return view


def _category_keyboard(view: StorefrontView) -> Any:
    rows = [
        [
            K.btn(
                f"{category.icon or E.SHOP} {category.name}",
                ShopCB(action="cat", ref=short_ref(category.id)),
            )
        ]
        for category in view.categories
    ]
    rows.append([K.home_button()])
    return K.stack(rows)


def _product_keyboard(category: CategoryView) -> Any:
    rows = [
        [
            K.btn(
                f"{product.icon or E.ROCKET} {product.name}",
                ShopCB(action="prod", ref=short_ref(product.id)),
            )
        ]
        for product in category.products
    ]
    rows.append([K.btn(T.BTN_BACK, NavCB(to="shop")), K.home_button()])
    return K.stack(rows)


def _plan_keyboard(product: ProductView) -> Any:
    """One package per row.

    Packages carry three facts (volume, duration, price) and cramming two per
    row truncates all of them at the 32-character label cap.
    """
    # Colour marks the recommendation, not the list. Every package blue
    # would be a wall of blue that recommends nothing; the featured one blue
    # is the shelf-edge label a customer actually reads.
    rows = [
        [
            K.btn(
                R.plan_button_label(plan),
                ShopCB(action="plan", ref=short_ref(plan.id)),
                style=K.GO if plan.is_featured else None,
            )
        ]
        for plan in product.plans
    ]
    rows.append([K.btn(T.BTN_BACK, NavCB(to="shop")), K.home_button()])
    return K.stack(rows)


async def open_storefront(
    message: Message, *, user: Any = None, scope: Any = None, services: Any = None, **_: Any
) -> None:
    """Entry point shared with the reply keyboard."""
    if user is None or scope is None:
        await answer(message, T.ERR_GENERIC)
        return
    view = await load_storefront(user=user, scope=scope, services=services)
    if not view.categories:
        await answer(message, T.SHOP_EMPTY)
        return
    body = f"{T.SHOP_TITLE.format(brand=brand_of(scope))}\n\n{T.SHOP_INTRO}"
    await answer(message, body, reply_markup=_category_keyboard(view))


@router.message(Command("shop"))
async def on_shop_command(
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await state.clear()
    await open_storefront(message, user=user, scope=scope, services=services)


@router.callback_query(NavCB.filter(F.to == "shop"))
async def on_open_shop(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await state.set_state(Purchase.browsing)
    # A renewal abandoned halfway leaves its target in the FSM data, and
    # nothing else clears it - so the next plan bought from the shop would
    # silently extend that service instead of adding a new one.
    await state.update_data(renew_of=None)
    await toast(query)
    if user is None or scope is None:
        return
    view = await load_storefront(user=user, scope=scope, services=services)
    if not view.categories:
        await safe_edit(query, T.SHOP_EMPTY, markup=K.single(K.home_button()))
        return
    body = f"{T.SHOP_TITLE.format(brand=brand_of(scope))}\n\n{T.SHOP_INTRO}"
    await safe_edit(query, body, markup=_category_keyboard(view))


@router.callback_query(ShopCB.filter(F.action == "cat"))
async def on_category(
    query: CallbackQuery,
    callback_data: ShopCB,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    view = await load_storefront(user=user, scope=scope, services=services)
    category = match_ref(list(view.categories), callback_data.ref, "id")
    if category is None:
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    if not category.products:
        await safe_edit(query, T.SHOP_EMPTY, markup=K.single(K.home_button()))
        return
    body = f"{category.icon or E.SHOP} <b>{category.name}</b>\n\n{T.SHOP_INTRO}"
    await safe_edit(query, body, markup=_product_keyboard(category))


@router.callback_query(ShopCB.filter(F.action == "prod"))
async def on_product(
    query: CallbackQuery,
    callback_data: ShopCB,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    view = await load_storefront(user=user, scope=scope, services=services)
    product = None
    for category in view.categories:
        product = match_ref(list(category.products), callback_data.ref, "id")
        if product is not None:
            break
    if product is None:
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    if not product.plans:
        await safe_edit(query, T.PRODUCT_NO_PLANS, markup=K.single(K.home_button()))
        return
    body = R.product_card(product)
    capacity = await capacity_line(scope, product.id)
    if capacity:
        body = f"{body}\n\n{capacity}"
    await safe_edit(query, body, markup=_plan_keyboard(product))


#: Below this many free places the line turns amber: worth buying now.
LOW_CAPACITY = 10


async def capacity_line(scope: Any, product_id: Any) -> str:
    """How much room the product's server has left, when the shop shows it.

    Only for a product bound to a server with a declared ceiling: an unbound
    product can land anywhere, and "unlimited" is not a number to show.
    """
    try:
        if not await scope.settings_service.get(SHOW_CAPACITY):
            return ""
        product = await scope.catalog_products.get(product_id)
        bound = getattr(product, "panel_id", None)
        if bound is None:
            return ""
        node = next(
            (n for n in await scope.nodes.list_every() if panel_id_for(n.id) == bound), None
        )
    except Exception:
        logger.warning("shop.capacity_unreadable", exc_info=True)
        return ""
    if node is None or node.capacity <= 0:
        return ""
    left = max(0, node.capacity - node.account_count)
    if left == 0:
        return T.CAPACITY_FULL
    if left <= LOW_CAPACITY:
        return T.CAPACITY_LOW.format(count=fa_digits(left))
    return T.CAPACITY_LEFT.format(count=fa_digits(left))
