""" "My services": list owned subscriptions, show one, hand over the config.

The subscription link is sent as a fresh message with <code> formatting
rather than edited into the existing card, so it survives navigation and can
be long-pressed to copy. Copying a config out of an edited-away message is a
real source of support tickets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers.common import (
    answer,
    match_ref,
    safe_edit,
    short_ref,
    toast,
)
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, SubCB

router = Router(name="dashboard")


def _list_keyboard(cards: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [
            K.btn(
                R.subscription_button_label(card),
                SubCB(action="view", ref=short_ref(card.subscription_id)),
            )
        ]
        for card in cards
    ]
    rows.append([K.btn(T.BTN_SHOP_NOW, NavCB(to="shop"), style=K.GO), K.home_button()])
    return K.stack(rows)


def _detail_keyboard(card: Any) -> InlineKeyboardMarkup:
    ref = short_ref(card.subscription_id)
    rows: list[list[Any]] = []
    if card.subscription_url:
        rows.append(
            [
                # The config is what the customer opened this screen for.
                K.btn(T.BTN_GET_CONFIG, SubCB(action="config", ref=ref), style=K.GO),
                K.btn(T.BTN_GET_QR, SubCB(action="qr", ref=ref)),
            ]
        )
    if card.is_renewable:
        # Green: it keeps a service alive, and it is the one action here
        # that ends with the customer paying us.
        rows.append([K.btn(T.BTN_RENEW, SubCB(action="renew", ref=ref), style=K.YES)])
    if card.subscription_url:
        rows.append([K.btn(T.BTN_ROTATE, SubCB(action="rotate", ref=ref))])
    rows.append([K.btn(T.BTN_BACK, NavCB(to="dashboard")), K.home_button()])
    return K.stack(rows)


async def _load(services: BotServices, user: Any) -> list[Any]:
    try:
        return await services.subscriptions.list_for_user(user.id)
    except Exception:
        return []


@router.message(Command("services"))
async def on_services_command(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return
    cards = await _load(services, user)
    if not cards:
        await answer(
            message,
            T.DASH_EMPTY,
            reply_markup=K.single(K.btn(T.BTN_SHOP_NOW, NavCB(to="shop"), style=K.GO)),
        )
        return
    await answer(message, T.DASH_TITLE, reply_markup=_list_keyboard(cards))


@router.callback_query(NavCB.filter(F.to == "dashboard"))
async def on_dashboard(
    query: CallbackQuery, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    await toast(query)
    if user is None:
        return
    cards = await _load(services, user)
    if not cards:
        await safe_edit(
            query,
            T.DASH_EMPTY,
            markup=K.single(K.btn(T.BTN_SHOP_NOW, NavCB(to="shop"), style=K.GO)),
        )
        return
    await safe_edit(query, T.DASH_TITLE, markup=_list_keyboard(cards))


@router.callback_query(SubCB.filter(F.action == "view"))
async def on_view(
    query: CallbackQuery,
    callback_data: SubCB,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    if user is None:
        return
    cards = await _load(services, user)
    card = match_ref(cards, callback_data.ref, "subscription_id")
    if card is None:
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    body = R.subscription_detail(card, now=datetime.now(UTC))
    await safe_edit(query, body, markup=_detail_keyboard(card))


@router.callback_query(SubCB.filter(F.action == "config"))
async def on_config(
    query: CallbackQuery,
    callback_data: SubCB,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query, T.TOAST_COPIED)
    if user is None or query.message is None:
        return
    cards = await _load(services, user)
    card = match_ref(cards, callback_data.ref, "subscription_id")
    # An InaccessibleMessage cannot be replied to, and a stale button is
    # exactly what the customer sees in both cases.
    if card is None or not card.subscription_url or not isinstance(query.message, Message):
        await toast(query, T.ERR_STALE_BUTTON, alert=True)
        return
    body = f"{T.CONFIG_CAPTION}\n\n<code>{card.subscription_url}</code>"
    await answer(query.message, body)


@router.callback_query(SubCB.filter(F.action == "qr"))
async def on_qr(
    query: CallbackQuery,
    callback_data: SubCB,
    services: BotServices,
    user: Any = None,
) -> None:
    """QR rendering is a Phase 6 concern (it needs an image pipeline).

    Until then we hand over the same link with the QR caption rather than
    showing a dead button.
    """
    await toast(query)
    if user is None or query.message is None:
        return
    cards = await _load(services, user)
    card = match_ref(cards, callback_data.ref, "subscription_id")
    # An InaccessibleMessage cannot be replied to, and a stale button is
    # exactly what the customer sees in both cases.
    if card is None or not card.subscription_url or not isinstance(query.message, Message):
        await toast(query, T.ERR_STALE_BUTTON, alert=True)
        return
    await answer(query.message, f"{T.QR_CAPTION}\n\n<code>{card.subscription_url}</code>")


@router.callback_query(SubCB.filter(F.action == "rotate"))
async def on_rotate_confirm(query: CallbackQuery, callback_data: SubCB) -> None:
    await toast(query)
    await safe_edit(
        query,
        T.ROTATE_CONFIRM,
        markup=K.stack(
            [
                # Rotating invalidates the link the customer is using right
                # now, so the confirm is the dangerous one here - not the cancel.
                [
                    K.btn(
                        T.BTN_CONFIRM,
                        SubCB(action="rotate_ok", ref=callback_data.ref),
                        style=K.NO,
                    )
                ],
                [K.btn(T.BTN_CANCEL, SubCB(action="view", ref=callback_data.ref), style=K.NO)],
            ]
        ),
    )


@router.callback_query(SubCB.filter(F.action == "rotate_ok"))
async def on_rotate(
    query: CallbackQuery,
    callback_data: SubCB,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    if user is None:
        return
    cards = await _load(services, user)
    card = match_ref(cards, callback_data.ref, "subscription_id")
    if card is None:
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    try:
        link = await services.subscriptions.rotate_link(user.id, card.subscription_id)
    except Exception:
        await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
        return
    if not link:
        await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
        return
    await safe_edit(
        query,
        f"{T.ROTATE_DONE}\n\n<code>{link}</code>",
        markup=K.single(K.btn(T.BTN_BACK, NavCB(to="dashboard"))),
    )
