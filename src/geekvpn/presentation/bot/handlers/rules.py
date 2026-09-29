"""The shop's rules, when the operator has switched them on.

The text is one of the editable screens, so the operator writes it from the
bot's admin menu like the greeting; the built-in version is only a starting
point nobody is expected to keep.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import copy as C
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import NavCB

router = Router(name="rules")


def _body(scope: Any) -> str | None:
    if not getattr(scope, "rules_enabled", False):
        return None
    return C.resolve(scope, "RULES")


@router.message(Command("rules"))
async def on_rules_command(message: Message, state: FSMContext, scope: Any = None) -> None:
    await state.clear()
    body = _body(scope)
    if body is None:
        await answer(message, T.ERR_UNKNOWN_COMMAND, reply_markup=K.main_menu())
        return
    await answer(message, body, reply_markup=K.single(K.home_button()))


@router.callback_query(NavCB.filter(F.to == "rules"))
async def on_rules(query: CallbackQuery, scope: Any = None) -> None:
    await toast(query)
    body = _body(scope)
    await safe_edit(query, body or T.ERR_STALE_BUTTON, markup=K.single(K.home_button()))
