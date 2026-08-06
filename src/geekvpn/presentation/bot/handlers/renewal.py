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


def _upgrade_keyboard(plans: list[Any], *, same_plan_id: Any) -> InlineKeyboardMarkup:
    """Same package first, then every other package in the product."""
    rows: list[list[Any]] = []
    for plan in plans:
        prefix = T.RENEW_SAME_PLAN if plan.plan_id == same_plan_id else ""
        label = R.plan_button_label(plan)
        rows.append(
            [K.btn(f"{prefix} {label}".strip(), ShopCB(action="plan", ref=short_ref(plan.plan_id)))]
        )
    rows.append([K.btn(T.BTN_BACK, NavCB(to="dashboard")), K.home_button()])
    return K.stack(rows)


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

    # Find the product this subscription belongs to, so the customer can
    # renew as-is or step up to a larger package in the same family.
    view = await load_storefront(user=user, scope=scope, services=services)
    owning_product = None
    for category in view.categories:
        for product in category.products:
            if any(p.plan_id == card.plan_id for p in product.plans):
                owning_product = product
                break
        if owning_product:
            break

    if owning_product is None or not owning_product.plans:
        await safe_edit(query, T.PLAN_UNAVAILABLE, markup=K.single(K.home_button()))
        return

    header = T.RENEW_INTRO.format(
        current=f"{card.product_name_fa} \u2014 {card.plan_name_fa}",
        expires=fa_date(card.expires_at) if card.expires_at else "\u2014",
    )
    body = f"{T.RENEW_TITLE}\n\n{header}"

    await state.set_state(Purchase.browsing)
    await safe_edit(
        query, body, markup=_upgrade_keyboard(list(owning_product.plans), same_plan_id=card.plan_id)
    )
