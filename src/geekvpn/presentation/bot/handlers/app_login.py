"""The bot's half of the Android app sign-in, and the list of signed-in devices.

`/start applogin_<code>` arrives here from `start.py` (checked before the
referral prefix). The account that opened the link gets a prompt naming the
device, with approve and cancel buttons; approving lets the waiting app
collect a normal customer session. See `AppLinkLogin` for the whole flow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.domain.identity.app_login import AppLoginStatus
from geekvpn.domain.identity.errors import (
    AppLoginAlreadyUsedError,
    AppLoginExpiredError,
    AppLoginNotFoundError,
    AppLoginNotYoursError,
)
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import AppLoginCB, DeviceCB
from geekvpn.presentation.bot.ui.fa import fa_datetime, isolate

logger = get_logger(__name__)

router = Router(name="app_login")

#: Iran has kept standard time all year since 2022, so a fixed offset is exact
#: and needs no tz database in the container.
_TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _tehran(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(_TEHRAN)


# -- /start applogin_<code> ----------------------------------------------------


async def handle_start(message: Message, *, scope: Any, user: Any, code: str) -> None:
    """Claim the request for this account and ask it to decide."""
    if scope is None or user is None:
        await answer(message, T.ERR_GENERIC)
        return
    if scope.reseller is not None:
        # The app is the platform's. In a reseller's bot this person is a
        # different customer, with a different wallet and services, and
        # signing the app into that account would show them the wrong ones.
        await answer(message, T.APP_LOGIN_WRONG_BOT)
        return

    try:
        request = await scope.app_link_login.claim(code, telegram_user_id=user.telegram_id)
    except AppLoginExpiredError:
        await answer(message, T.APP_LOGIN_EXPIRED)
        return
    except AppLoginAlreadyUsedError:
        await answer(message, T.APP_LOGIN_USED)
        return
    except AppLoginNotFoundError:
        await answer(message, T.APP_LOGIN_NOT_FOUND)
        return

    body = T.APP_LOGIN_PROMPT.format(
        device=isolate(request.device_name),
        platform=isolate(request.platform),
        time=fa_datetime(_tehran(request.created_at)),
    )
    await answer(message, body, reply_markup=_decision_keyboard(request.id))


def _decision_keyboard(request_id: uuid.UUID) -> InlineKeyboardMarkup:
    return K.stack(
        [
            [
                K.btn(
                    T.BTN_APP_LOGIN_APPROVE,
                    AppLoginCB(rid=request_id.hex, act="ok"),
                    style=K.YES,
                ),
                K.btn(T.BTN_APP_LOGIN_DENY, AppLoginCB(rid=request_id.hex, act="no"), style=K.NO),
            ]
        ]
    )


@router.callback_query(AppLoginCB.filter())
async def on_decision(
    query: CallbackQuery, callback_data: AppLoginCB, scope: Any = None, user: Any = None
) -> None:
    if scope is None or user is None:
        await toast(query, T.ERR_GENERIC, alert=True)
        return
    try:
        request_id = uuid.UUID(hex=callback_data.rid)
    except ValueError:
        await toast(query, T.APP_LOGIN_NOT_FOUND, alert=True)
        return

    try:
        status = await scope.app_link_login.decide(
            request_id,
            telegram_user_id=user.telegram_id,
            approve=callback_data.act == "ok",
        )
    except AppLoginNotYoursError:
        await toast(query, T.APP_LOGIN_NOT_YOURS, alert=True)
        return
    except AppLoginExpiredError:
        await toast(query)
        await safe_edit(query, T.APP_LOGIN_EXPIRED)
        return
    except AppLoginAlreadyUsedError:
        await toast(query)
        await safe_edit(query, T.APP_LOGIN_USED)
        return
    except AppLoginNotFoundError:
        await toast(query, T.APP_LOGIN_NOT_FOUND, alert=True)
        return

    await toast(query)
    approved = status is AppLoginStatus.APPROVED
    await safe_edit(query, T.APP_LOGIN_APPROVED if approved else T.APP_LOGIN_DENIED)


# -- signed-in devices (from the profile screen) --------------------------------


async def _devices_screen(scope: Any, user: Any) -> tuple[str, InlineKeyboardMarkup]:
    devices = await scope.app_link_login.devices(user.id)
    if not devices:
        return T.DEVICES_EMPTY, K.stack([], back_to="profile")
    lines = [
        T.DEVICE_LINE.format(
            name=isolate(device.name), time=fa_datetime(_tehran(device.last_used_at))
        )
        for device in devices
    ]
    rows = [
        [
            K.btn(
                T.BTN_DEVICE_DISCONNECT.format(name=device.name),
                DeviceCB(action="cut", ref=device.session_id.hex),
                style=K.NO,
            )
        ]
        for device in devices
    ]
    return f"{T.DEVICES_TITLE}\n\n" + "\n".join(lines), K.stack(rows, back_to="profile")


@router.callback_query(DeviceCB.filter(F.action == "list"))
async def on_devices(query: CallbackQuery, scope: Any = None, user: Any = None) -> None:
    await toast(query)
    if scope is None or user is None:
        return
    body, markup = await _devices_screen(scope, user)
    await safe_edit(query, body, markup=markup)


@router.callback_query(DeviceCB.filter(F.action == "cut"))
async def on_disconnect(
    query: CallbackQuery, callback_data: DeviceCB, scope: Any = None, user: Any = None
) -> None:
    if scope is None or user is None:
        await toast(query)
        return
    try:
        session_id = uuid.UUID(hex=callback_data.ref)
    except ValueError:
        await toast(query)
        return
    if await scope.app_link_login.disconnect(user.id, session_id):
        logger.info("app_login.device_disconnected", session_id=str(session_id))
        await toast(query, T.DEVICE_DISCONNECTED)
    else:
        await toast(query)
    body, markup = await _devices_screen(scope, user)
    await safe_edit(query, body, markup=markup)
