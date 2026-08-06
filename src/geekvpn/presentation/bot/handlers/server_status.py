"""Public server health board.

Exists to deflect "is it down?" tickets. Shows every node's health and load,
and is intentionally readable by users with no active subscription -- someone
deciding whether to buy should be able to see the fleet is healthy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.services import BotServices
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB, StatusCB

router = Router(name="server_status")


def _keyboard() -> InlineKeyboardMarkup:
    return K.stack(
        [
            [K.btn(T.BTN_REFRESH, StatusCB(action="refresh", ref="-"))],
            [K.home_button()],
        ]
    )


async def _render(services: BotServices) -> str:
    try:
        rows = await services.servers.rows()
    except Exception:
        rows = []
    return R.server_status(rows, checked_at=datetime.now(UTC))


@router.message(Command("status"))
async def on_status_command(message: Message, state: FSMContext, services: BotServices) -> None:
    await state.clear()
    await answer(message, await _render(services), reply_markup=_keyboard())


@router.callback_query(NavCB.filter(F.to == "status"))
async def on_status(query: CallbackQuery, state: FSMContext, services: BotServices) -> None:
    await state.clear()
    await toast(query)
    await safe_edit(query, await _render(services), markup=_keyboard())


@router.callback_query(StatusCB.filter(F.action == "refresh"))
async def on_refresh(query: CallbackQuery, services: BotServices) -> None:
    await toast(query, T.TOAST_REFRESHED)
    await safe_edit(query, await _render(services), markup=_keyboard())
