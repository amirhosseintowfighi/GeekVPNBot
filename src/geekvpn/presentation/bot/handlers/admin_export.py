"""Orders and customers as an Excel file, from the bot's admin menu.

Behind the analytics export permission: the file is every customer's
Telegram id, name and spending, which a support agent has no reason to carry
around in a chat.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from geekvpn.domain.identity.permissions import Permission
from geekvpn.infrastructure.analytics.xlsx_export import build_workbook
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.admin import _guard
from geekvpn.presentation.bot.handlers.common import toast
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui.callbacks import AdminCB
from geekvpn.presentation.bot.ui.fa import fa_date

logger = get_logger("bot.admin_export")

router = Router(name="admin_export")


def _build(container: Container) -> bytes:
    with container.sync_sessions() as session:
        return build_workbook(session, now=container.clock.now())


@router.callback_query(AdminCB.filter(F.action == "export"))
async def on_export(
    query: CallbackQuery, container: Container, scope: Any = None, user: Any = None
) -> None:
    admin = await _guard(scope, user)
    if admin is None or not admin.has_permission(Permission.ANALYTICS_EXPORT):
        await toast(query, A.EXPORT_NOT_ALLOWED, alert=True)
        return
    await toast(query, A.EXPORT_WORKING)
    if not isinstance(query.message, Message):
        return
    try:
        payload = await asyncio.to_thread(_build, container)
    except Exception:
        logger.exception("admin.export_failed")
        await query.message.answer(A.EXPORT_FAILED)
        return
    now = container.clock.now()
    await query.message.answer_document(
        BufferedInputFile(payload, filename=f"geekvpn-{now:%Y%m%d-%H%M}.xlsx"),
        caption=A.EXPORT_CAPTION.format(date=fa_date(now)),
    )
