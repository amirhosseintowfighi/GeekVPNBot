"""Notification settings.

Each switch redraws in place, so the keyboard is the state display -- no
"saved" screen, no extra tap. The toggle is applied optimistically to the
loaded object and persisted before redraw, so what the customer sees is
always what was written.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.application.bot.read_models import NotificationPreferences
from geekvpn.application.bot.services import BotServices
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, SettingsCB

router = Router(name="settings")

SWITCHES: tuple[tuple[str, str], ...] = (
    ("expiry", T.SET_NOTIFY_EXPIRY),
    ("traffic", T.SET_NOTIFY_TRAFFIC),
    ("promos", T.SET_NOTIFY_PROMOS),
    ("news", T.SET_NOTIFY_NEWS),
    ("quiet_hours", T.SET_QUIET_HOURS),
)


def _keyboard(preferences: NotificationPreferences) -> InlineKeyboardMarkup:
    values = preferences.as_dict()
    rows = [
        [
            K.btn(
                K.toggle_label(label, enabled=bool(values.get(key, False))),
                SettingsCB(action="toggle", key=key, value="-"),
            )
        ]
        for key, label in SWITCHES
    ]
    rows.append([K.home_button()])
    return K.stack(rows)


async def _load(services: BotServices, user: Any) -> NotificationPreferences:
    try:
        return await services.preferences.load(user.id)
    except Exception:
        return NotificationPreferences()


@router.message(Command("settings"))
async def on_settings_command(
    message: Message, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    if user is None:
        await answer(message, T.ERR_GENERIC)
        return
    preferences = await _load(services, user)
    await answer(message, R.settings_body(preferences), reply_markup=_keyboard(preferences))


@router.callback_query(NavCB.filter(F.to == "settings"))
async def on_settings(
    query: CallbackQuery, state: FSMContext, services: BotServices, user: Any = None
) -> None:
    await state.clear()
    await toast(query)
    if user is None:
        return
    preferences = await _load(services, user)
    await safe_edit(query, R.settings_body(preferences), markup=_keyboard(preferences))


@router.callback_query(SettingsCB.filter(F.action == "toggle"))
async def on_toggle(
    query: CallbackQuery,
    callback_data: SettingsCB,
    services: BotServices,
    user: Any = None,
) -> None:
    if user is None:
        await toast(query)
        return

    current = await _load(services, user)
    updated = current.with_toggled(callback_data.key)

    if updated is current:
        # Unknown key -- a stale keyboard from an older deploy.
        await toast(query, T.TOAST_NOTHING_CHANGED)
        return

    try:
        await services.preferences.save(user.id, updated)
    except Exception:
        await toast(query, T.ERR_GENERIC, alert=True)
        return

    await toast(query, T.SETTINGS_SAVED)
    await safe_edit(query, R.settings_body(updated), markup=_keyboard(updated))
