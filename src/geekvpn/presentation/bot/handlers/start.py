"""Registration and onboarding.

Design stance: Telegram has *already* authenticated this person and the
identity middleware has already created their account. So "registration" here
is not a gate -- it is a short, skippable welcome that collects the one thing
we cannot infer (what they want to be called) and then gets out of the way.

A returning user never sees any of it.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers.admin import is_admin
from geekvpn.presentation.bot.handlers.common import (
    answer,
    brand_of,
    display_name_of,
    safe_edit,
    toast,
)
from geekvpn.presentation.bot.handlers.menu import render_home
from geekvpn.presentation.bot.states import Registration
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import stickers as S
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB
from geekvpn.presentation.bot.ui.fa import isolate, normalize_input

router = Router(name="start")

MIN_NAME = 2
MAX_NAME = 50


@router.message(CommandStart())
async def on_start(
    message: Message,
    state: FSMContext,
    services: BotServices,
    scope: Any = None,
    user: Any = None,
    is_new_user: bool = False,
    suspended: bool = False,
    bot: Any = None,
    stickers: Any = None,
) -> None:
    """`/start`, including `/start ref_XXXX` deep links.

    Clears FSM state unconditionally. `/start` is the universal escape hatch:
    whatever broken flow a user is stuck in, this always returns them to a
    known-good screen.
    """
    await state.clear()

    if suspended:
        await answer(message, T.ERR_SUSPENDED)
        return
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return

    # The first thing a new customer sees. Best effort, and before the text
    # rather than after: a greeting that arrives under its own sticker reads
    # as a greeting, one that arrives above it reads as an afterthought.
    await S.send(bot, message.chat.id, stickers, "welcome")

    if is_new_user:
        name = display_name_of(user)
        await answer(
            message,
            T.WELCOME_NEW.format(name=isolate(name), brand=brand_of(scope)),
            reply_markup=K.main_menu(),
        )
        await state.set_state(Registration.display_name)
        builder = InlineKeyboardBuilder()
        builder.row(K.btn(T.BTN_SKIP, NavCB(to="skip_name")))
        await answer(message, T.ASK_DISPLAY_NAME, reply_markup=builder.as_markup())
        return

    await answer(
        message,
        T.WELCOME_BACK.format(name=isolate(display_name_of(user))),
        reply_markup=K.main_menu(),
    )
    body, markup = await render_home(
        user=user, services=services, is_admin=await is_admin(scope, user)
    )
    await answer(message, body, reply_markup=markup)


@router.message(Registration.display_name, F.text)
async def on_display_name(
    message: Message,
    state: FSMContext,
    services: BotServices,
    user: Any = None,
) -> None:
    raw = normalize_input(message.text or "")

    if len(raw) < MIN_NAME:
        await answer(message, T.NAME_TOO_SHORT)
        return
    if len(raw) > MAX_NAME:
        await answer(message, T.NAME_TOO_LONG)
        return

    if user is not None:
        await services.profiles.set_display_name(user.id, raw)

    await state.clear()
    await answer(message, T.REGISTRATION_DONE.format(name=isolate(raw)))
    if user is not None:
        body, markup = await render_home(user=user, services=services, name=raw)
        await answer(message, body, reply_markup=markup)


@router.callback_query(Registration.display_name, NavCB.filter(F.to == "skip_name"))
async def on_skip_name(
    query: CallbackQuery,
    state: FSMContext,
    services: BotServices,
    scope: Any = None,
    user: Any = None,
) -> None:
    await state.clear()
    await toast(query, T.TOAST_DONE)
    if user is None:
        return
    body, markup = await render_home(
        user=user, services=services, is_admin=await is_admin(scope, user)
    )
    await safe_edit(query, body, markup=markup)


@router.message(Command("help"))
async def on_help(message: Message, services: BotServices, user: Any = None) -> None:
    await answer(message, T.SUPPORT_INTRO, reply_markup=K.main_menu())
