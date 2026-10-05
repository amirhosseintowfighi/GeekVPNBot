"""A message pinned at the top of every customer's chat with the bot.

The operator sends it once, in whatever form - text, photo, video, file - and
it is copied into each customer's chat and pinned there, so the shop's
announcement stays the first thing they see however far the chat scrolls.

Run as a background task rather than inside the handler: thousands of chats
at the rate Telegram tolerates is minutes, and a callback answered minutes
late has long since been abandoned. Which message went to whom is kept in the
cache, so "take it down" later knows exactly what to unpin.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.notifications.enums import AudienceKind
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.api.admin_common import read_scope
from geekvpn.presentation.bot.handlers.admin import _guard
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui.callbacks import AdminCB
from geekvpn.presentation.bot.ui.fa import fa_digits

logger = get_logger("bot.admin_pin")

router = Router(name="admin_pin")

#: Telegram allows about thirty messages a second to different chats; a copy
#: and a pin are two calls, so this keeps comfortably inside it.
PER_SECOND = 12
#: Customer id to the message pinned in their chat, as JSON.
PINNED_KEY = "pin:last"
#: Set while a run is going, so two operators cannot start two at once.
RUNNING_KEY = "pin:running"
PINNED_TTL = 60 * 60 * 24 * 365


class PinFlow(StatesGroup):
    composing = State()


async def _sender(scope: Any, user: Any) -> Any | None:
    admin = await _guard(scope, user)
    if admin is None or not admin.has_permission(Permission.BROADCAST_SEND):
        return None
    return admin


async def _audience(container: Container) -> list[int]:
    def work(sync: SyncScope) -> list[int]:
        return sync.audiences.resolve(AudienceKind.ALL)

    return await read_scope(container, work)


@router.callback_query(AdminCB.filter(F.action == "pin"))
async def on_pin(
    query: CallbackQuery, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    if await _sender(scope, user) is None:
        await toast(query, A.PIN_NOT_ALLOWED, alert=True)
        return
    await toast(query)
    await state.set_state(PinFlow.composing)
    await safe_edit(
        query,
        A.PIN_ASK,
        markup=K.stack(
            [
                [K.btn(A.BTN_UNPIN, AdminCB(action="unpin"))],
                [K.btn(A.BTN_BACK, AdminCB(action="menu"))],
            ]
        ),
    )


@router.message(PinFlow.composing)
async def on_pin_message(
    message: Message,
    state: FSMContext,
    container: Container,
    scope: Any = None,
    user: Any = None,
    **_: Any,
) -> None:
    if await _sender(scope, user) is None:
        await state.clear()
        await answer(message, A.PIN_NOT_ALLOWED)
        return
    audience = await _audience(container)
    await state.update_data(pin_chat=message.chat.id, pin_message=message.message_id)
    await answer(
        message,
        A.PIN_CONFIRM.format(count=fa_digits(len(audience))),
        reply_markup=K.stack(
            [
                [K.btn(A.BTN_PIN_GO, AdminCB(action="pin_go"), style=K.YES)],
                [K.btn(A.BTN_BACK, AdminCB(action="menu"))],
            ]
        ),
    )


@router.callback_query(AdminCB.filter(F.action == "pin_go"))
async def on_pin_go(
    query: CallbackQuery,
    state: FSMContext,
    container: Container,
    bot: Any,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _sender(scope, user) is None:
        await toast(query, A.PIN_NOT_ALLOWED, alert=True)
        return
    data = await state.get_data()
    await state.clear()
    source_chat, source_message = data.get("pin_chat"), data.get("pin_message")
    if not isinstance(source_chat, int) or not isinstance(source_message, int):
        await toast(query, A.PIN_NOT_ALLOWED, alert=True)
        return
    if not await container.cache.add_if_absent(RUNNING_KEY, "1", ttl_seconds=3 * 60 * 60):
        await toast(query, A.PIN_BUSY, alert=True)
        return
    await toast(query)
    await safe_edit(query, A.PIN_STARTED)
    audience = await _audience(container)
    asyncio.create_task(  # noqa: RUF006 - runs to completion on its own; the operator is told
        _pin_everywhere(
            bot, container, audience, source_chat, source_message, report_to=source_chat
        )
    )


async def _pin_everywhere(
    bot: Any,
    container: Container,
    audience: list[int],
    source_chat: int,
    source_message: int,
    *,
    report_to: int,
) -> None:
    pinned: dict[str, int] = {}
    failed = 0
    try:
        for index, chat_id in enumerate(audience):
            try:
                copied = await bot.copy_message(
                    chat_id=chat_id, from_chat_id=source_chat, message_id=source_message
                )
                await bot.pin_chat_message(
                    chat_id=chat_id, message_id=copied.message_id, disable_notification=True
                )
                pinned[str(chat_id)] = copied.message_id
            except Exception:
                # Blocked the bot, deleted their account: nothing to retry.
                logger.debug("pin.not_delivered", chat=chat_id)
                failed += 1
            if index % PER_SECOND == PER_SECOND - 1:
                await asyncio.sleep(1)
        await container.cache.set(PINNED_KEY, json.dumps(pinned), ttl_seconds=PINNED_TTL)
    finally:
        await container.cache.delete(RUNNING_KEY)
    try:
        await bot.send_message(
            report_to,
            A.PIN_DONE.format(pinned=fa_digits(len(pinned)), failed=fa_digits(failed)),
        )
    except Exception:
        logger.warning("pin.report_failed", exc_info=True)


@router.callback_query(AdminCB.filter(F.action == "unpin"))
async def on_unpin(
    query: CallbackQuery,
    state: FSMContext,
    container: Container,
    bot: Any,
    scope: Any = None,
    user: Any = None,
) -> None:
    if await _sender(scope, user) is None:
        await toast(query, A.PIN_NOT_ALLOWED, alert=True)
        return
    await state.clear()
    await toast(query)
    stored = await container.cache.get(PINNED_KEY)
    pinned: dict[str, int] = json.loads(stored) if stored else {}
    if not pinned:
        await safe_edit(
            query, A.UNPIN_NONE, markup=K.single(K.btn(A.BTN_BACK, AdminCB(action="menu")))
        )
        return
    await safe_edit(query, A.PIN_STARTED)
    report_to = query.from_user.id
    asyncio.create_task(  # noqa: RUF006 - runs to completion on its own; the operator is told
        _unpin_everywhere(bot, container, pinned, report_to=report_to)
    )


async def _unpin_everywhere(
    bot: Any, container: Container, pinned: dict[str, int], *, report_to: int
) -> None:
    removed = 0
    for index, (chat_id, message_id) in enumerate(pinned.items()):
        try:
            await bot.unpin_chat_message(chat_id=int(chat_id), message_id=message_id)
            removed += 1
        except Exception:
            # Already unpinned by the customer, or the chat is gone.
            logger.debug("pin.unpin_skipped", chat=chat_id)
        if index % PER_SECOND == PER_SECOND - 1:
            await asyncio.sleep(1)
    await container.cache.delete(PINNED_KEY)
    try:
        await bot.send_message(report_to, A.UNPIN_DONE.format(count=fa_digits(removed)))
    except Exception:
        logger.warning("pin.report_failed", exc_info=True)
