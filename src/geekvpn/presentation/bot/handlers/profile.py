"""Profile: identity, loyalty tier progress, display-name editing.

Shows *why* a tier matters (the cashback it unlocks) and how far the next one
is, rather than presenting a bare badge. A progress bar toward a concrete
reward is the whole point of the tier system.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import WalletSnapshot
from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers.common import (
    answer,
    next_tier,
    safe_edit,
    tier_emoji,
    tier_label,
    tier_of,
    toast,
)
from geekvpn.presentation.bot.states import Profile
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, ProfileCB
from geekvpn.presentation.bot.ui.fa import isolate, normalize_input

router = Router(name="profile")

MIN_NAME = 2
MAX_NAME = 50


def _keyboard() -> InlineKeyboardMarkup:
    return K.stack(
        [
            [K.btn(T.BTN_EDIT_NAME, ProfileCB(action="edit_name", ref="-"))],
            [K.btn(f"\u2699\ufe0f {T.MENU_SETTINGS}", NavCB(to="settings"))],
            [K.home_button()],
        ]
    )


async def _render(services: BotServices, user: Any) -> str:
    try:
        summary = await services.profiles.summary(user.id)
    except Exception:
        return T.ERR_GENERIC
    try:
        snapshot = await services.wallet.snapshot(user.id)
    except Exception:
        snapshot = WalletSnapshot()

    tier = tier_of(snapshot.lifetime_spend)
    body = R.profile(
        summary,
        tier_label=tier_label(tier),
        tier_emoji=tier_emoji(tier),
        balance=snapshot.balance,
    )
    following, threshold = next_tier(tier)
    progress = R.tier_progress(
        spend=snapshot.lifetime_spend,
        next_threshold=threshold,
        next_tier_label=tier_label(following) if following else None,
    )
    return f"{body}\n\n{progress}"


@router.message(Command("profile"))
async def on_profile_command(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return
    await answer(message, await _render(services, user), reply_markup=_keyboard())


@router.callback_query(NavCB.filter(F.to == "profile"))
async def on_profile(
    query: CallbackQuery, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    await toast(query)
    if user is None:
        return
    await safe_edit(query, await _render(services, user), markup=_keyboard())


@router.callback_query(ProfileCB.filter(F.action == "edit_name"))
async def on_edit_name(query: CallbackQuery, state: FSMContext) -> None:
    await toast(query)
    await state.set_state(Profile.editing_name)
    await safe_edit(
        query,
        T.ASK_DISPLAY_NAME,
        markup=K.single(K.btn(T.BTN_CANCEL, NavCB(to="profile"), style=K.NO)),
    )


@router.message(Profile.editing_name, F.text)
async def on_name_text(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    raw = normalize_input(message.text or "")
    if len(raw) < MIN_NAME:
        await answer(message, T.NAME_TOO_SHORT)
        return
    if len(raw) > MAX_NAME:
        await answer(message, T.NAME_TOO_LONG)
        return
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return

    await services.profiles.set_display_name(user.id, raw)
    await state.clear()
    await answer(message, T.PROFILE_NAME_UPDATED.format(name=isolate(raw)))
    await answer(message, await _render(services, user), reply_markup=_keyboard())
