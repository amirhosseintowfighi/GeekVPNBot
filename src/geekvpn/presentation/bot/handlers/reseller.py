"""The reseller area, and the door into it.

Two audiences on one button. Someone who is not a reseller sees an invitation
and an application form; someone who is sees their console - what they owe,
what each package costs them, what they charge, and a way to create a service.

Identity is the Telegram account, the same way the operator area works. There
is no second login here and there must not be: a password typed into a chat is
a password in somebody's message history forever.

The price screen shows cost beside retail on purpose. A reseller choosing what
to charge is comparing their margin, and a screen that shows only one of the
two numbers is a screen they price from memory against.
"""

from __future__ import annotations

import uuid
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from geekvpn.application.resellers.applications import AlreadyApplied
from geekvpn.domain.resellers.errors import InsufficientCredit, ResellerSuspended
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import answer, customer_message, safe_edit, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import reseller_text as R
from geekvpn.presentation.bot.ui.callbacks import NavCB, ResellerCB
from geekvpn.presentation.bot.ui.fa import fa_number, normalize_input, toman

logger = get_logger("bot.reseller")

router = Router(name="reseller")


class ResellerFlow(StatesGroup):
    naming_shop = State()
    describing = State()
    pricing = State()


async def _mine(scope: Any, user: Any) -> Any:
    """The reseller record behind this Telegram account, or None.

    By Telegram id, through the admin account: a reseller signs in to the panel
    with a username, and identifies themselves here by being the same person.
    """
    telegram_id = getattr(user, "telegram_id", None)
    if telegram_id is None:
        return None
    admin = await scope.admins.get_by_telegram_id(telegram_id)
    if admin is None:
        return None
    try:
        return await scope.reseller_service.for_admin(admin.id)
    except Exception:
        return None


# -- the door ---------------------------------------------------------------


async def open_area(message: Message, *, user: Any = None, scope: Any = None, **_: Any) -> None:
    """The one entry point, from the persistent keyboard."""
    if user is None or scope is None:
        return

    reseller = await _mine(scope, user)
    if reseller is not None:
        await answer(message, _console(reseller), reply_markup=_console_keyboard())
        return

    pending = await scope.reseller_applications.status_for(user.telegram_id)
    if pending is not None:
        await answer(message, R.APPLICATION_PENDING, reply_markup=K.main_menu())
        return

    await answer(message, R.INVITE, reply_markup=_invite_keyboard())


def _invite_keyboard() -> Any:
    return K.stack(
        [[K.btn(R.BTN_APPLY, ResellerCB(action="apply"), style=K.YES)]],
        home=True,
    )


def _console_keyboard() -> Any:
    return K.stack(
        [
            [K.btn(R.BTN_SELL, ResellerCB(action="plans"), style=K.YES)],
            [K.btn(R.BTN_PRICES, ResellerCB(action="prices"), style=K.GO)],
            [K.btn(R.BTN_LEDGER, ResellerCB(action="ledger"), style=K.GO)],
        ],
        home=True,
    )


def _console(reseller: Any) -> str:
    if reseller.in_arrears:
        state = R.CONSOLE_ARREARS.format(debt=toman(abs(reseller.balance_amount)))
    else:
        state = R.CONSOLE_BALANCE.format(balance=toman(reseller.balance_amount))
    return R.CONSOLE.format(
        name=reseller.name_fa,
        state=state,
        discount=fa_number(reseller.discount_percent),
    )


# -- applying ---------------------------------------------------------------


@router.callback_query(ResellerCB.filter(F.action == "apply"))
async def on_apply(query: CallbackQuery, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(ResellerFlow.naming_shop)
    await safe_edit(query, R.ASK_SHOP_NAME, markup=K.single(K.btn(R.BTN_CANCEL, NavCB(to="home"), style=K.NO)))


@router.message(ResellerFlow.naming_shop, F.text)
async def on_shop_name(message: Message, state: FSMContext) -> None:
    name = normalize_input(message.text or "")
    if len(name) < 2:
        await answer(message, R.NAME_TOO_SHORT)
        return
    await state.update_data(shop_name=name[:128])
    await state.set_state(ResellerFlow.describing)
    await answer(message, R.ASK_CONTACT)


@router.message(ResellerFlow.describing, F.text)
async def on_contact(
    message: Message, state: FSMContext, user: Any = None, scope: Any = None, **_: Any
) -> None:
    if user is None or scope is None:
        return
    data = await state.get_data()
    await state.clear()

    try:
        await scope.reseller_applications.apply(
            telegram_id=user.telegram_id,
            name_fa=str(data.get("shop_name", "")),
            contact_fa=normalize_input(message.text or "")[:256],
        )
    except AlreadyApplied:
        await answer(message, R.APPLICATION_PENDING, reply_markup=K.main_menu())
        return
    except Exception as failure:
        logger.exception("bot.reseller_apply_failed", telegram_id=user.telegram_id)
        await answer(message, customer_message(failure), reply_markup=K.main_menu())
        return

    await answer(message, R.APPLICATION_SENT, reply_markup=K.main_menu())


# -- the console ------------------------------------------------------------


@router.callback_query(ResellerCB.filter(F.action == "prices"))
async def on_prices(
    query: CallbackQuery, services: Any = None, user: Any = None, scope: Any = None, **_: Any
) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    reseller = await _mine(scope, user)
    if reseller is None:
        await safe_edit(query, R.NOT_A_RESELLER, markup=K.single(K.home_button()))
        return

    rows = await scope.reseller_sales.price_list(
        reseller.id, await scope.catalog_plans.list_all(published_only=True)
    )
    await safe_edit(
        query,
        R.price_table(rows),
        markup=K.stack(
            [[K.btn(R.BTN_SET_PRICE, ResellerCB(action="setprice"), style=K.GO)]],
            back_to="reseller",
        ),
    )


@router.callback_query(ResellerCB.filter(F.action == "ledger"))
async def on_ledger(
    query: CallbackQuery, user: Any = None, scope: Any = None, **_: Any
) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    reseller = await _mine(scope, user)
    if reseller is None:
        await safe_edit(query, R.NOT_A_RESELLER, markup=K.single(K.home_button()))
        return

    entries = await scope.reseller_service.history(reseller.id, limit=15)
    await safe_edit(query, R.ledger(entries), markup=K.back_only("reseller"))


@router.callback_query(NavCB.filter(F.to == "reseller"))
async def on_back(query: CallbackQuery, user: Any = None, scope: Any = None, **_: Any) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    reseller = await _mine(scope, user)
    if reseller is None:
        await safe_edit(query, R.NOT_A_RESELLER, markup=K.single(K.home_button()))
        return
    await safe_edit(query, _console(reseller), markup=_console_keyboard())


# -- selling ----------------------------------------------------------------


@router.callback_query(ResellerCB.filter(F.action == "plans"))
async def on_plans(query: CallbackQuery, user: Any = None, scope: Any = None, **_: Any) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    reseller = await _mine(scope, user)
    if reseller is None:
        await safe_edit(query, R.NOT_A_RESELLER, markup=K.single(K.home_button()))
        return

    rows = await scope.reseller_sales.price_list(
        reseller.id, await scope.catalog_plans.list_all(published_only=True)
    )
    if not rows:
        await safe_edit(query, R.NO_PLANS, markup=K.back_only("reseller"))
        return

    buttons = [
        [
            K.btn(
                R.plan_button(row),
                ResellerCB(action="sell", ref=str(row["plan_id"])[:32]),
                style=K.GO,
            )
        ]
        for row in rows
    ]
    await safe_edit(query, R.CHOOSE_PLAN, markup=K.stack(buttons, back_to="reseller"))


@router.callback_query(ResellerCB.filter(F.action == "sell"))
async def on_sell(
    query: CallbackQuery,
    callback_data: ResellerCB,
    user: Any = None,
    scope: Any = None,
    **_: Any,
) -> None:
    await toast(query)
    if user is None or scope is None:
        return
    reseller = await _mine(scope, user)
    if reseller is None:
        await safe_edit(query, R.NOT_A_RESELLER, markup=K.single(K.home_button()))
        return

    rows = await scope.reseller_sales.price_list(
        reseller.id, await scope.catalog_plans.list_all(published_only=True)
    )
    match = next((r for r in rows if str(r["plan_id"]).startswith(callback_data.ref)), None)
    if match is None:
        await safe_edit(query, R.PLAN_GONE, markup=K.back_only("reseller"))
        return

    try:
        sale = await scope.reseller_sales.sell(
            reseller_id=reseller.id, plan_id=uuid.UUID(str(match["plan_id"]))
        )
    except InsufficientCredit as failure:
        await safe_edit(
            query,
            R.NOT_ENOUGH_CREDIT.format(shortfall=toman(failure.shortfall)),
            markup=K.back_only("reseller"),
        )
        return
    except ResellerSuspended:
        await safe_edit(query, R.SUSPENDED, markup=K.single(K.home_button()))
        return
    except Exception as failure:
        logger.exception("bot.reseller_sale_failed", reseller=str(reseller.id))
        await safe_edit(query, customer_message(failure), markup=K.back_only("reseller"))
        return

    await safe_edit(
        query,
        R.sold(sale, plan_name=str(match["name"])),
        markup=K.back_only("reseller"),
    )


__all__ = ["open_area", "router"]
