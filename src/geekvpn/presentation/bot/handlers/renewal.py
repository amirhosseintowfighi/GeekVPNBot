"""Renewal.

Renewal is deliberately routed back through the normal purchase review rather
than being a one-tap charge. The price may have changed, a campaign may now
apply, and the customer is entitled to see the invoice before paying -- a
silent auto-charge on a VPN subscription is how chargebacks happen.

The renewal entry point pre-selects the same package and jumps straight to
review, so it is still two taps.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers.common import (
    match_ref,
    safe_edit,
    short_ref,
    toast,
)
from geekvpn.presentation.bot.handlers.shop import load_storefront
from geekvpn.presentation.bot.states import Purchase
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, ShopCB, SubCB
from geekvpn.presentation.bot.ui.fa import fa_date

router = Router(name="renewal")


def _upgrade_keyboard(view: Any, *, same_plan_id: Any, own_product_id: Any) -> InlineKeyboardMarkup:
    """Everything on sale today, the customer's own product first.

    It used to be the plans of one product, found by looking up the plan the
    subscription was sold on - so two customers could not renew at all: the one
    whose package had since been retired, and the one who adopted an account
    with a pasted link, which has no plan behind it by design. Both got "this
    package no longer exists" and a home button.

    A wider list is also the upgrade path. Moving from 20GB to 100GB is a
    renewal onto a different package, and the only thing that ever stopped it
    was this keyboard.
    """
    rows: list[list[Any]] = []
    for product in _products(view, own_first=own_product_id):
        for plan in product.plans:
            label = R.plan_button_label(plan)
            if plan.id == same_plan_id:
                label = f"{T.RENEW_SAME_PLAN} {label}"
            elif product.id != own_product_id:
                # Named, because outside their own product the package name
                # alone ("سه ماهه") says nothing about what they are buying.
                label = f"{product.name} · {label}"
            rows.append([K.btn(label, ShopCB(action="plan", ref=short_ref(plan.id)))])
    rows.append([K.btn(T.BTN_BACK, NavCB(to="dashboard")), K.home_button()])
    return K.stack(rows)


def _products(view: Any, *, own_first: Any) -> list[Any]:
    products = [
        product
        for category in view.categories
        for product in category.products
        if product.plans
    ]
    # Stable, so the storefront's own order survives; it only lifts the family
    # the customer is already in.
    return sorted(products, key=lambda product: product.id != own_first)


@router.callback_query(SubCB.filter(F.action == "renew"))
async def on_renew(
    query: CallbackQuery,
    callback_data: SubCB,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
    scope: Any = None,
) -> None:
    await toast(query)
    if user is None or scope is None:
        return

    try:
        cards = await services.subscriptions.list_for_user(user.id)
    except Exception:
        cards = []
    card = match_ref(cards, callback_data.ref, "subscription_id")
    if card is None:
        await safe_edit(query, T.RENEW_NOTHING, markup=K.single(K.home_button()))
        return

    # Which family they are in, if it is still on sale - used only to sort the
    # list, never to limit it.
    view = await load_storefront(user=user, scope=scope, services=services)
    owning_product = next(
        (
            product
            for category in view.categories
            for product in category.products
            if any(p.id == card.plan_id for p in product.plans)
        ),
        None,
    )

    if not any(product.plans for category in view.categories for product in category.products):
        await safe_edit(query, T.PLAN_UNAVAILABLE, markup=K.single(K.home_button()))
        return

    header = T.RENEW_INTRO.format(
        # An adopted account has no order behind it and therefore no package
        # name; its panel username is the only thing that identifies it.
        current=f"{card.product_name_fa} \u2014 {card.plan_name_fa}".strip(" \u2014")
        or card.remote_username
        or "\u2014",
        expires=fa_date(card.expires_at) if card.expires_at else "\u2014",
    )
    body = f"{T.RENEW_TITLE}\n\n{header}"

    await state.set_state(Purchase.browsing)
    # What turns the purchase that follows into a renewal. Read again at the
    # moment of payment, so every screen in between stays the ordinary one.
    await state.update_data(renew_of=str(card.subscription_id))
    await safe_edit(
        query,
        body,
        markup=_upgrade_keyboard(
            view,
            same_plan_id=card.plan_id,
            own_product_id=owning_product.id if owning_product else None,
        ),
    )
