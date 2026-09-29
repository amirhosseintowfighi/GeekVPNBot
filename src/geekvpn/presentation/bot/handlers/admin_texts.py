"""Rewriting the bot's own screens, from inside the bot.

The same screens a reseller may rewrite for their shop, stored for the main
bot in one setting. Editing where the result is read means the operator sees
it the way a customer will, formatting and all, instead of in a text box.

A text must keep its `{placeholders}`. Deleting `{name}` from the greeting is
a style choice; deleting `{amount}` from a payment screen is a customer who
does not know what to transfer, so the edit is refused and the operator is
told which ones went missing.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from geekvpn.application.platform.settings_service import RULES_ENABLED, TEXT_OVERRIDES
from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.bot.handlers.admin import _guard
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui import copy as C
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui.callbacks import AdminCB

router = Router(name="admin_texts")


class TextFlow(StatesGroup):
    writing = State()


async def _editor(scope: Any, user: Any) -> Any | None:
    admin = await _guard(scope, user)
    if admin is None or not admin.has_permission(Permission.SETTINGS_WRITE):
        return None
    return admin


async def _overrides(scope: Any) -> dict[str, str]:
    return dict(await scope.settings_service.get(TEXT_OVERRIDES))


def _list_markup(rules_on: bool) -> Any:
    rows = [[K.btn(label, AdminCB(action="text", ref=key))] for key, label in C.EDITABLE.items()]
    rows.append(
        [
            K.btn(
                A.BTN_RULES_ON if rules_on else A.BTN_RULES_OFF,
                AdminCB(action="rules_toggle"),
            )
        ]
    )
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="menu"))])
    return K.stack(rows)


def _screen(key: str, overrides: dict[str, str]) -> str:
    names = C.placeholders(key)
    return A.TEXT_SCREEN.format(
        label=C.EDITABLE[key],
        state=A.TEXT_CUSTOM if key in overrides else A.TEXT_DEFAULT,
        current=overrides.get(key) or C.default_for(key),
        placeholders=(
            A.TEXT_PLACEHOLDERS.format(names=" ".join(f"{{{n}}}" for n in names))
            if names
            else A.TEXT_NO_PLACEHOLDERS
        ),
    )


def _text_markup(key: str, customised: bool) -> Any:
    rows = [[K.btn(A.BTN_TEXT_EDIT, AdminCB(action="text_edit", ref=key), style=K.GO)]]
    if customised:
        rows.append([K.btn(A.BTN_TEXT_RESET, AdminCB(action="text_reset", ref=key))])
    rows.append([K.btn(A.BTN_BACK, AdminCB(action="texts"))])
    return K.stack(rows)


async def _save(scope: Any, admin: Any, overrides: dict[str, str]) -> None:
    await scope.settings_service.set(
        TEXT_OVERRIDES.key, overrides, actor_id=admin.id, actor_label=admin.username
    )
    await scope.session.commit()


@router.callback_query(AdminCB.filter(F.action == "texts"))
async def on_texts(
    query: CallbackQuery, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    await state.clear()
    if await _editor(scope, user) is None:
        await toast(query, A.TEXTS_NOT_ALLOWED, alert=True)
        return
    await toast(query)
    rules_on = await scope.settings_service.get(RULES_ENABLED)
    await safe_edit(query, A.TEXTS_TITLE, markup=_list_markup(rules_on))


@router.callback_query(AdminCB.filter(F.action == "text"))
async def on_text(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    if await _editor(scope, user) is None or callback_data.ref not in C.EDITABLE:
        await toast(query, A.TEXTS_NOT_ALLOWED, alert=True)
        return
    await toast(query)
    overrides = await _overrides(scope)
    key = callback_data.ref
    await safe_edit(query, _screen(key, overrides), markup=_text_markup(key, key in overrides))


@router.callback_query(AdminCB.filter(F.action == "text_edit"))
async def on_text_edit(
    query: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _editor(scope, user) is None or callback_data.ref not in C.EDITABLE:
        await toast(query, A.TEXTS_NOT_ALLOWED, alert=True)
        return
    await toast(query)
    await state.set_state(TextFlow.writing)
    await state.update_data(text_key=callback_data.ref)
    await safe_edit(
        query,
        A.TEXT_ASK,
        markup=K.single(K.btn(A.BTN_BACK, AdminCB(action="text", ref=callback_data.ref))),
    )


@router.message(TextFlow.writing, F.text)
async def on_text_written(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None, **_: Any
) -> None:
    admin = await _editor(scope, user)
    key = str((await state.get_data()).get("text_key", ""))
    if admin is None or key not in C.EDITABLE:
        await state.clear()
        await answer(message, A.TEXTS_NOT_ALLOWED)
        return
    # `html_text` keeps the operator's bold and links as they typed them.
    written = (getattr(message, "html_text", None) or message.text or "").strip()
    missing = [name for name in C.placeholders(key) if f"{{{name}}}" not in written]
    if missing:
        # Stay in the state: the next message is the corrected text.
        await answer(
            message, A.TEXT_MISSING.format(names=" ".join(f"{{{n}}}" for n in missing))
        )
        return
    overrides = await _overrides(scope)
    overrides[key] = written
    await _save(scope, admin, overrides)
    await state.clear()
    await answer(message, A.TEXT_SAVED, reply_markup=_text_markup(key, True))


@router.callback_query(AdminCB.filter(F.action == "text_reset"))
async def on_text_reset(
    query: CallbackQuery, callback_data: AdminCB, scope: Any = None, user: Any = None
) -> None:
    admin = await _editor(scope, user)
    if admin is None or callback_data.ref not in C.EDITABLE:
        await toast(query, A.TEXTS_NOT_ALLOWED, alert=True)
        return
    overrides = await _overrides(scope)
    overrides.pop(callback_data.ref, None)
    await _save(scope, admin, overrides)
    await toast(query, A.TEXT_RESET_DONE)
    key = callback_data.ref
    await safe_edit(query, _screen(key, overrides), markup=_text_markup(key, False))


@router.callback_query(AdminCB.filter(F.action == "rules_toggle"))
async def on_rules_toggle(query: CallbackQuery, scope: Any = None, user: Any = None) -> None:
    admin = await _editor(scope, user)
    if admin is None:
        await toast(query, A.TEXTS_NOT_ALLOWED, alert=True)
        return
    turned_on = not await scope.settings_service.get(RULES_ENABLED)
    await scope.settings_service.set(
        RULES_ENABLED.key, turned_on, actor_id=admin.id, actor_label=admin.username
    )
    await scope.session.commit()
    await toast(query)
    await safe_edit(query, A.TEXTS_TITLE, markup=_list_markup(turned_on))
