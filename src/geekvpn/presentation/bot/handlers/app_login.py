"""The bot's half of the Android app sign-in, the signed-in devices, and the
app username and password.

`/start applogin_<code>` arrives here from `start.py` (checked before the
referral prefix). The account that opened the link gets a prompt naming the
device, with approve and cancel buttons; approving lets the waiting app
collect a normal customer session. See `AppLinkLogin` for the whole flow.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from geekvpn.domain.identity.app_login import AppLoginStatus
from geekvpn.domain.identity.errors import (
    AppLoginAlreadyUsedError,
    AppLoginExpiredError,
    AppLoginNotFoundError,
    AppLoginNotYoursError,
    AppPasswordWeakError,
    AppUsernameInvalidError,
    AppUsernameTakenError,
)
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.handlers.common import answer, safe_edit, toast
from geekvpn.presentation.bot.states import Profile
from geekvpn.presentation.bot.ui import keyboards as K
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import AppLoginCB, AppPasswordCB, DeviceCB
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


# -- app username and password (from the profile screen) -----------------------


def _password_menu(username: str | None) -> tuple[str, InlineKeyboardMarkup]:
    if username is None:
        return T.APP_CREDS_INTRO, K.stack(
            [[K.btn(T.BTN_APP_CREDS_SET, AppPasswordCB(action="set"), style=K.YES)]],
            back_to="profile",
        )
    return T.APP_CREDS_CURRENT.format(username=escape(username)), K.stack(
        [
            [K.btn(T.BTN_APP_CREDS_CHANGE, AppPasswordCB(action="set"))],
            [K.btn(T.BTN_APP_CREDS_REMOVE, AppPasswordCB(action="remove"), style=K.NO)],
        ],
        back_to="profile",
    )


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return K.single(K.btn(T.BTN_CANCEL, AppPasswordCB(action="menu"), style=K.NO))


@router.callback_query(AppPasswordCB.filter(F.action == "menu"))
async def on_password_menu(
    query: CallbackQuery, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    await state.clear()
    await toast(query)
    if scope is None or user is None:
        return
    if scope.reseller is not None:
        await safe_edit(query, T.APP_LOGIN_WRONG_BOT, markup=K.stack([], back_to="profile"))
        return
    body, markup = _password_menu(await scope.app_password_login.username_of(user.id))
    await safe_edit(query, body, markup=markup)


@router.callback_query(AppPasswordCB.filter(F.action == "set"))
async def on_password_set(query: CallbackQuery, state: FSMContext, scope: Any = None) -> None:
    await toast(query)
    if scope is None or scope.reseller is not None:
        return
    await state.set_state(Profile.app_username)
    await safe_edit(query, T.APP_CREDS_ASK_USERNAME, markup=_cancel_keyboard())


@router.message(Profile.app_username, F.text)
async def on_app_username(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    if scope is None or user is None:
        await answer(message, T.ERR_GENERIC)
        return
    try:
        username = await scope.app_password_login.is_available(
            message.text or "", user_id=user.id
        )
    except AppUsernameInvalidError:
        await answer(message, T.APP_CREDS_USERNAME_INVALID, reply_markup=_cancel_keyboard())
        return
    except AppUsernameTakenError:
        await answer(message, T.APP_CREDS_USERNAME_TAKEN, reply_markup=_cancel_keyboard())
        return
    await state.update_data(app_username=username)
    await state.set_state(Profile.app_password)
    await answer(message, T.APP_CREDS_ASK_SECOND, reply_markup=_cancel_keyboard())


@router.message(Profile.app_password, F.text)
async def on_app_password(
    message: Message, state: FSMContext, scope: Any = None, user: Any = None
) -> None:
    password = message.text or ""
    # Out of the chat history before anything else, whatever happens next.
    with contextlib.suppress(TelegramAPIError):
        await message.delete()
    if scope is None or user is None:
        await answer(message, T.ERR_GENERIC)
        return
    username = (await state.get_data()).get("app_username")
    if not username:
        await state.set_state(Profile.app_username)
        await answer(message, T.APP_CREDS_ASK_USERNAME, reply_markup=_cancel_keyboard())
        return
    try:
        stored = await scope.app_password_login.set_credentials(
            user.id, username=username, password=password
        )
    except AppPasswordWeakError:
        await answer(message, T.APP_CREDS_TOO_SHORT, reply_markup=_cancel_keyboard())
        return
    except AppUsernameTakenError:
        await state.set_state(Profile.app_username)
        await answer(message, T.APP_CREDS_USERNAME_TAKEN, reply_markup=_cancel_keyboard())
        return
    except AppUsernameInvalidError:
        await state.clear()
        await answer(message, T.APP_LOGIN_WRONG_BOT)
        return
    await state.clear()
    logger.info("app_password.set", user_id=str(user.id))
    await answer(
        message,
        T.APP_CREDS_SAVED.format(username=escape(stored)),
        reply_markup=K.stack([], back_to="profile"),
    )


@router.callback_query(AppPasswordCB.filter(F.action == "remove"))
async def on_password_remove(query: CallbackQuery) -> None:
    await toast(query)
    await safe_edit(
        query,
        T.APP_CREDS_REMOVE_CONFIRM,
        markup=K.stack(
            [
                [
                    K.btn(
                        T.BTN_APP_CREDS_REMOVE_OK,
                        AppPasswordCB(action="remove_ok"),
                        style=K.NO,
                    )
                ]
            ],
            back_to="profile",
        ),
    )


@router.callback_query(AppPasswordCB.filter(F.action == "remove_ok"))
async def on_password_remove_ok(query: CallbackQuery, scope: Any = None, user: Any = None) -> None:
    if scope is None or user is None:
        await toast(query)
        return
    await scope.app_password_login.remove_credentials(user.id)
    await toast(query, T.APP_CREDS_REMOVED)
    body, markup = _password_menu(None)
    await safe_edit(query, body, markup=markup)
