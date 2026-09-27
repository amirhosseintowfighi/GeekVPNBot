"""What a customer may change about their own service.

Auto-renewal from the wallet, a name of their choosing, and handing the
service to somebody else. Each is a switch the shop can turn off in settings;
the buttons disappear with it, and a stale button is refused by the adapter.

Transferring asks twice. It cannot be undone by the customer - the service
leaves their list - so the second screen names both the service and the
recipient before anything moves.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from geekvpn.application.bot.services import BotServices
from geekvpn.domain.base.errors import DomainError
from geekvpn.presentation.bot.handlers.common import answer, match_ref, safe_edit, toast
from geekvpn.presentation.bot.handlers.dashboard import show_detail
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, SubCB
from geekvpn.presentation.bot.ui.fa import en_digits, normalize_input

router = Router(name="service_owner")

#: `-` alone clears the name, back to the plan's.
CLEAR_NAME = "-"


class OwnerFlow(StatesGroup):
    naming = State()
    transferring = State()


async def _card(services: BotServices, user: Any, ref: str) -> Any | None:
    cards = await services.subscriptions.list_for_user(user.id)
    return match_ref(cards, ref, "subscription_id")


def _back(ref: str) -> Any:
    return K.single(K.btn(T.BTN_BACK, SubCB(action="view", ref=ref)))


@router.callback_query(SubCB.filter(F.action == "auto"))
async def on_auto_renew(
    query: CallbackQuery, callback_data: SubCB, services: BotServices, user: Any = None
) -> None:
    if user is None or services.ownership is None:
        await toast(query)
        return
    card = await _card(services, user, callback_data.ref)
    if card is None:
        await toast(query)
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    try:
        updated = await services.ownership.set_auto_renew(
            user.id, card.subscription_id, enabled=not card.auto_renew
        )
    except PermissionError:
        await toast(query, T.FEATURE_OFF, alert=True)
        return
    await toast(query, T.AUTO_RENEW_TURNED_ON if updated.auto_renew else T.AUTO_RENEW_TURNED_OFF)
    await show_detail(query, services, updated)


# -- rename --------------------------------------------------------------------


@router.callback_query(SubCB.filter(F.action == "rename"))
async def on_rename_start(query: CallbackQuery, callback_data: SubCB, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(OwnerFlow.naming)
    await state.update_data(owner_ref=callback_data.ref)
    await safe_edit(query, T.RENAME_ASK, markup=_back(callback_data.ref))


@router.message(OwnerFlow.naming, F.text)
async def on_rename_text(
    message: Message, state: FSMContext, services: BotServices, user: Any = None, **_: Any
) -> None:
    data = await state.get_data()
    ref = str(data.get("owner_ref", ""))
    if user is None or services.ownership is None:
        await state.clear()
        return
    raw = " ".join((message.text or "").split())
    name = None if raw == CLEAR_NAME else raw
    card = await _card(services, user, ref)
    if card is None:
        await state.clear()
        await answer(message, T.ERR_STALE_BUTTON)
        return
    try:
        updated = await services.ownership.rename(user.id, card.subscription_id, name=name)
    except PermissionError:
        await state.clear()
        await answer(message, T.FEATURE_OFF)
        return
    except DomainError:
        # Too long. Stay in the state so the next message is the retry.
        await answer(message, T.RENAME_TOO_LONG)
        return
    await state.clear()
    await answer(
        message,
        f"{T.RENAME_DONE}\n\n{R.subscription_button_label(updated)}",
        reply_markup=_back(ref),
    )


# -- transfer ------------------------------------------------------------------


@router.callback_query(SubCB.filter(F.action == "transfer"))
async def on_transfer_start(query: CallbackQuery, callback_data: SubCB, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(OwnerFlow.transferring)
    await state.update_data(owner_ref=callback_data.ref)
    await safe_edit(query, T.TRANSFER_ASK, markup=_back(callback_data.ref))


@router.message(OwnerFlow.transferring, F.text)
async def on_transfer_target(
    message: Message, state: FSMContext, services: BotServices, user: Any = None, **_: Any
) -> None:
    data = await state.get_data()
    ref = str(data.get("owner_ref", ""))
    typed = en_digits(normalize_input(message.text or "")).strip()
    if not typed.isdigit():
        await answer(message, T.TRANSFER_BAD_ID)
        return
    to_id = int(typed)
    if user is None:
        await state.clear()
        return
    if to_id == user.telegram_id:
        await answer(message, T.TRANSFER_SELF)
        return
    card = await _card(services, user, ref)
    if card is None:
        await state.clear()
        await answer(message, T.ERR_STALE_BUTTON)
        return
    # The recipient travels in the FSM, not the button: 64 bytes of callback
    # data cannot carry a ref and a Telegram id, and a button someone else
    # could craft should not decide who receives a service anyway.
    await state.update_data(owner_to=to_id)
    await answer(
        message,
        T.TRANSFER_CONFIRM.format(name=R.subscription_button_label(card), to_id=to_id),
        reply_markup=K.stack(
            [
                [K.btn(T.BTN_TRANSFER_CONFIRM, SubCB(action="xfer_ok", ref=ref), style=K.NO)],
                [K.btn(T.BTN_CANCEL, SubCB(action="view", ref=ref))],
            ]
        ),
    )


@router.callback_query(SubCB.filter(F.action == "xfer_ok"))
async def on_transfer_confirm(
    query: CallbackQuery,
    callback_data: SubCB,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    await toast(query)
    data = await state.get_data()
    await state.clear()
    to_id = data.get("owner_to")
    if user is None or services.ownership is None or not isinstance(to_id, int):
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    card = await _card(services, user, callback_data.ref)
    if card is None:
        await safe_edit(query, T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
        return
    try:
        await services.ownership.transfer(user.id, card.subscription_id, to_telegram_id=to_id)
    except PermissionError:
        await safe_edit(query, T.FEATURE_OFF, markup=K.single(K.home_button()))
        return
    except LookupError:
        await safe_edit(query, T.TRANSFER_NO_SUCH_USER, markup=_back(callback_data.ref))
        return
    except DomainError:
        await safe_edit(query, T.ERR_GENERIC, markup=K.single(K.home_button()))
        return
    await safe_edit(
        query,
        T.TRANSFER_DONE,
        markup=K.single(K.btn(T.MENU_DASHBOARD, NavCB(to="dashboard"))),
    )
