"""Last-resort handlers. Registered after every other router.

Two jobs: translate reply-keyboard taps into the inline flows, and make sure
an unrecognised message gets a helpful Persian nudge instead of silence. A bot
that ignores you feels broken even when it is working perfectly.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers import (
    dashboard,
    faq,
    profile,
    referral,
    server_status,
    settings,
    shop,
    support,
    wallet,
)
from geekvpn.presentation.bot.handlers.common import answer, toast
from geekvpn.presentation.bot.handlers.menu import render_home
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T

router = Router(name="fallback")


@router.message(F.text == T.MENU_SHOP)
async def tap_shop(message: Message, state: FSMContext, **kwargs: Any) -> None:
    await state.clear()
    await shop.open_storefront(
        message,
        user=kwargs.get("user"),
        scope=kwargs.get("scope"),
        services=kwargs.get("services"),
    )


@router.message(F.text == T.MENU_DASHBOARD)
async def tap_dashboard(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await dashboard.on_services_command(message, state, services, user)


@router.message(F.text == T.MENU_WALLET)
async def tap_wallet(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await wallet.on_wallet_command(message, state, services, user)


@router.message(F.text == T.MENU_REFERRAL)
async def tap_referral(
    message: Message,
    state: FSMContext,
    services: BotServices,
    bot: Any = None,
    user: Any = None,
) -> None:
    await referral.on_referral_command(message, state, services, bot, user)


@router.message(F.text == T.MENU_SUPPORT)
async def tap_support(message: Message, state: FSMContext) -> None:
    await support.on_support_command(message, state)


@router.message(F.text == T.MENU_PROFILE)
async def tap_profile(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await profile.on_profile_command(message, state, services, user)


@router.message(F.text == T.MENU_FAQ)
async def tap_faq(message: Message, state: FSMContext) -> None:
    await faq.on_faq_command(message, state)


@router.message(F.text == T.MENU_SETTINGS)
async def tap_settings(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await settings.on_settings_command(message, state, services, user)


@router.message(F.text == T.MENU_STATUS)
async def tap_status(message: Message, state: FSMContext, services: BotServices) -> None:
    await server_status.on_status_command(message, state, services)


@router.message()
async def unknown_message(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    """Anything we did not understand.

    Clears state first: reaching here usually means the user abandoned a flow
    mid-way, and leaving them in a dangling FSM state would swallow their
    next message too.
    """
    await state.clear()
    await answer(message, T.ERR_UNKNOWN_COMMAND, reply_markup=K.main_menu())
    if user is not None:
        body, markup = await render_home(user=user, services=services)
        await answer(message, body, reply_markup=markup)


@router.callback_query()
async def unknown_callback(query: CallbackQuery) -> None:
    """A button from a deploy whose callback schema no longer exists."""
    await toast(query, T.ERR_STALE_BUTTON, alert=True)
