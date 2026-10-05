"""The top twenty customers on four ladders, from the bot's admin menu.

Telegram ids are shown in full: this is an operator's screen, and the id is
what they paste into "find a customer" next.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery

from geekvpn.infrastructure.analytics.top_customers import Ladder, Rung, top
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.bot.handlers.admin import _guard
from geekvpn.presentation.bot.handlers.common import safe_edit, toast
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui.callbacks import AdminCB
from geekvpn.presentation.bot.ui.fa import fa_digits, toman

router = Router(name="admin_top")


def _ladders() -> Any:
    rows = [
        [K.btn(label, AdminCB(action="top_list", ref=key))] for key, label in A.TOP_LADDERS.items()
    ]
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    return K.stack(rows)


def _render(ladder: Ladder, rungs: list[Rung]) -> str:
    if not rungs:
        return f"{A.TOP_LADDERS[ladder.value]}\n\n{A.TOP_EMPTY}"
    lines = [
        A.TOP_ROW.format(
            rank=fa_digits(rank),
            telegram_id=rung.telegram_id,
            name=rung.name,
            value=fa_digits(rung.value) if ladder is Ladder.SERVICES else toman(rung.value),
        )
        for rank, rung in enumerate(rungs, start=1)
    ]
    return f"<b>{A.TOP_LADDERS[ladder.value]}</b>\n\n" + "\n".join(lines)


@router.callback_query(AdminCB.filter(F.action == "top"))
async def on_top(query: CallbackQuery, scope: Any = None, user: Any = None) -> None:
    if await _guard(scope, user) is None:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    await toast(query)
    await safe_edit(query, A.TOP_TITLE, markup=_ladders())


@router.callback_query(AdminCB.filter(F.action == "top_list"))
async def on_top_list(
    query: CallbackQuery,
    callback_data: AdminCB,
    container: Container,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _guard(scope, user) is None or callback_data.ref not in A.TOP_LADDERS:
        await toast(query, A.NOT_AN_ADMIN, alert=True)
        return
    await toast(query)
    ladder = Ladder(callback_data.ref)

    def read() -> list[Rung]:
        with container.sync_sessions() as session:
            return top(session, ladder, now=container.clock.now())

    rungs = await asyncio.to_thread(read)
    await safe_edit(
        query,
        _render(ladder, rungs),
        markup=K.single(K.btn(A.BTN_BACK, AdminCB(action="top"))),
    )
