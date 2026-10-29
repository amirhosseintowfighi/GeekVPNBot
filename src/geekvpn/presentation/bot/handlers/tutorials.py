"""The Geek apps to download, and connection tutorials, one per device.

Downloads come first: they are links to the latest release of each Geek app,
read from the same GitHub releases the apps update from, so this screen never
offers a version the app would call outdated.

Tutorials are written by the operator.

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
from geekvpn.infrastructure.client_downloads import ClientDownload, client_downloads
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import GuideCB, NavCB

logger = get_logger("bot.tutorials")

router = Router(name="tutorials")


async def written(scope: Any) -> dict[str, dict[str, str]]:
    if scope is None:
        return {}
    try:
        return dict(await scope.settings_service.get(TUTORIALS))
    except Exception:
        return {}


async def downloads(scope: Any) -> list[ClientDownload]:
    """The apps' download links. A GitHub that cannot be reached costs the links,
    not the screen: the tutorials under them still work."""
    if scope is None:
        return []
    try:
        container = scope.container
        return await client_downloads(container.settings.app_release, container.cache)
    except Exception:
        logger.warning("bot.downloads_unavailable", exc_info=True)
        return []


def _picker(tutorials: dict[str, Any], links: list[ClientDownload]) -> Any:
    rows: list[list[Any]] = [
        [K.url_btn(_download_label(link), link.url, style=K.GO)] for link in links
    ]
    buttons = [
        K.btn(T.DEVICE_LABELS[device], GuideCB(device=device))
        for device in TUTORIAL_DEVICES
        if device in tutorials
    ]
    rows.extend(buttons[i : i + 2] for i in range(0, len(buttons), 2))
    rows.append([K.home_button()])
    return K.stack(rows)


def _download_label(link: ClientDownload) -> str:
    name = T.DOWNLOAD_APP_LABELS.get(link.platform, link.platform)
    if link.version:
        return T.DOWNLOAD_BUTTON_VERSION.format(app=name, version=link.version)
    return T.DOWNLOAD_BUTTON.format(app=name)


def _screen(tutorials: dict[str, Any], links: list[ClientDownload]) -> str:
    parts = [T.GUIDE_TITLE]
    if links:
        parts.append(T.GUIDE_DOWNLOADS)
    if tutorials:
        parts.append(T.GUIDE_TUTORIALS)
    return "\n\n".join(parts)


async def show_guide(message: Message, scope: Any = None) -> None:
    """Entry point shared with the reply keyboard and /guide."""
    tutorials, links = await written(scope), await downloads(scope)
    if not tutorials and not links:
        await answer(message, T.GUIDE_NONE)
        return
    await answer(message, _screen(tutorials, links), reply_markup=_picker(tutorials, links))


@router.message(Command("guide"))
async def on_guide_command(message: Message, scope: Any = None) -> None:
    await show_guide(message, scope)


@router.callback_query(NavCB.filter(F.to == "guide"))
async def on_guide(query: CallbackQuery, scope: Any = None) -> None:
    await toast(query)
    tutorials, links = await written(scope), await downloads(scope)
    if not tutorials and not links:
        await safe_edit(query, T.GUIDE_NONE, markup=K.single(K.home_button()))
        return
    await safe_edit(query, _screen(tutorials, links), markup=_picker(tutorials, links))


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
