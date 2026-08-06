"""FAQ browser: sections -> question -> answer."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.presentation.bot.faq_content import (
    ENTRIES_BY_KEY,
    FAQ,
    SECTIONS_BY_KEY,
)
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import FaqCB, NavCB

router = Router(name="faq")


def _section_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [K.btn(f"{section.icon} {section.title_fa}", FaqCB(action="sec", ref=section.key))]
        for section in FAQ
    ]
    rows.append([K.btn(f"\U0001f4ac {T.MENU_SUPPORT}", NavCB(to="support")), K.home_button()])
    return K.stack(rows)


def _entry_keyboard(section_key: str) -> InlineKeyboardMarkup:
    section = SECTIONS_BY_KEY[section_key]
    rows = [
        [K.btn(entry.question_fa, FaqCB(action="q", ref=entry.key))] for entry in section.entries
    ]
    rows.append([K.btn(T.BTN_BACK, NavCB(to="faq")), K.home_button()])
    return K.stack(rows)


@router.message(Command("faq"))
async def on_faq_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await answer(message, f"{T.FAQ_TITLE}\n\n{T.FAQ_INTRO}", reply_markup=_section_keyboard())


@router.callback_query(NavCB.filter(F.to == "faq"))
async def on_faq(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await toast(query)
    await safe_edit(query, f"{T.FAQ_TITLE}\n\n{T.FAQ_INTRO}", markup=_section_keyboard())


@router.callback_query(FaqCB.filter(F.action == "sec"))
async def on_section(query: CallbackQuery, callback_data: FaqCB) -> None:
    await toast(query)
    section = SECTIONS_BY_KEY.get(callback_data.ref)
    if section is None:
        await safe_edit(query, T.FAQ_NOT_FOUND, markup=K.single(K.home_button()))
        return
    body = f"{section.icon} <b>{section.title_fa}</b>\n\n{T.FAQ_INTRO}"
    await safe_edit(query, body, markup=_entry_keyboard(section.key))


@router.callback_query(FaqCB.filter(F.action == "q"))
async def on_entry(query: CallbackQuery, callback_data: FaqCB) -> None:
    await toast(query)
    entry = ENTRIES_BY_KEY.get(callback_data.ref)
    if entry is None:
        await safe_edit(query, T.FAQ_NOT_FOUND, markup=K.single(K.home_button()))
        return

    owning = next((s.key for s in FAQ if any(e.key == entry.key for e in s.entries)), None)
    body = f"<b>{entry.question_fa}</b>\n\n{entry.answer_fa}\n\n{T.FAQ_STILL_STUCK}"
    rows = []
    if owning:
        rows.append([K.btn(T.BTN_BACK, FaqCB(action="sec", ref=owning))])
    rows.append([K.btn(f"\U0001f4ac {T.MENU_SUPPORT}", NavCB(to="support")), K.home_button()])
    await safe_edit(query, body, markup=K.stack(rows))
