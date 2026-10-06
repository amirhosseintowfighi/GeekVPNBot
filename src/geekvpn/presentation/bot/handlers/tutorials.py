"""Connection tutorials, one per device, written by the operator.

A text, or a photo or video with its caption - whatever the operator sent,
sent back as it was. Telegram file ids are stored rather than the files: the
bot that received them can send them again, and nothing is re-uploaded.

Only devices with a tutorial are offered. A picker listing five devices of
which two lead to "nothing here yet" teaches the customer not to look.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from geekvpn.application.platform.settings_service import TUTORIAL_DEVICES, TUTORIALS
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import GuideCB, NavCB

router = Router(name="tutorials")


async def written(scope: Any) -> dict[str, dict[str, str]]:
    if scope is None:
        return {}
    try:
        return dict(await scope.settings_service.get(TUTORIALS))
    except Exception:
        return {}


def _picker(tutorials: dict[str, Any]) -> Any:
    buttons = [
        K.btn(T.DEVICE_LABELS[device], GuideCB(device=device))
        for device in TUTORIAL_DEVICES
        if device in tutorials
    ]
    markup = K.grid(buttons, width=2)
    markup.inline_keyboard.append([K.home_button()])
    return markup


@router.message(Command("guide"))
async def on_guide_command(message: Message, scope: Any = None) -> None:
    tutorials = await written(scope)
    if not tutorials:
        await answer(message, T.GUIDE_NONE)
        return
    await answer(message, T.GUIDE_PICK, reply_markup=_picker(tutorials))


@router.callback_query(NavCB.filter(F.to == "guide"))
async def on_guide(query: CallbackQuery, scope: Any = None) -> None:
    await toast(query)
    tutorials = await written(scope)
    if not tutorials:
        await safe_edit(query, T.GUIDE_NONE, markup=K.single(K.home_button()))
        return
    await safe_edit(query, T.GUIDE_PICK, markup=_picker(tutorials))


@router.callback_query(GuideCB.filter())
async def on_device(query: CallbackQuery, callback_data: GuideCB, scope: Any = None) -> None:
    await toast(query)
    entry = (await written(scope)).get(callback_data.device)
    if entry is None or not isinstance(query.message, Message):
        await safe_edit(query, T.GUIDE_NONE, markup=K.single(K.home_button()))
        return
    back = K.single(K.btn(T.BTN_BACK, NavCB(to="guide")))
    kind, body, file_id = entry.get("kind"), entry.get("text", ""), entry.get("file_id", "")
    if kind == "photo":
        await query.message.answer_photo(file_id, caption=body or None, reply_markup=back)
    elif kind == "video":
        await query.message.answer_video(file_id, caption=body or None, reply_markup=back)
    else:
        await query.message.answer(body, reply_markup=back)
