"""Which operator may press which button, decided in one place.

The panel has always checked a permission per endpoint. The bot's operator
area checked only that the caller was staff, so every role passed: a VIEWER,
read-only by definition, could approve a receipt, credit a wallet, suspend a
customer or extend a service from Telegram, and SUPPORT could approve the
payments the panel keeps from them.

Each operator button (`AdminCB.action`) and each step of an operator
conversation (an FSM state) names the permission the panel requires for the
same act. `AdminAccess` sits on the admin routers and refuses a call before
the handler runs, so a handler that forgets to check is still covered. A
button with no entry here is refused, and a test lists any that are missing.

The handlers keep their own `_guard` and role checks: this is the floor, not
a replacement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from geekvpn.domain.identity.admin import Admin
from geekvpn.domain.identity.permissions import AdminRole, Permission
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui.callbacks import AdminCB

logger = get_logger("bot.admin_access")

#: `None` is "any member of staff": screens that show nothing on their own.
ACTION_PERMISSIONS: dict[str, Permission | None] = {
    "menu": None,
    # payments and receipts
    "payments": Permission.PAYMENTS_READ,
    "payment": Permission.PAYMENTS_READ,
    "approve": Permission.PAYMENTS_APPROVE,
    "reject": Permission.PAYMENTS_APPROVE,
    "fake": Permission.PAYMENTS_APPROVE,
    "fake_ok": Permission.PAYMENTS_APPROVE,
    # resellers' wallet top-ups are payments to us
    "topups": Permission.PAYMENTS_READ,
    "topup": Permission.PAYMENTS_READ,
    "topup_ok": Permission.PAYMENTS_APPROVE,
    "topup_no": Permission.PAYMENTS_APPROVE,
    # support
    "tickets": Permission.TICKETS_READ,
    "ticket": Permission.TICKETS_READ,
    "reply": Permission.TICKETS_REPLY,
    "close": Permission.TICKETS_REPLY,
    # reseller applications
    "apps": Permission.RESELLERS_READ,
    "app": Permission.RESELLERS_READ,
    "app_ok": Permission.RESELLERS_WRITE,
    "app_no": Permission.RESELLERS_WRITE,
    # customers
    "find": Permission.USERS_READ,
    "message": Permission.USERS_WRITE,
    "suspend": Permission.USERS_SUSPEND,
    "reinstate": Permission.USERS_SUSPEND,
    "wallet_add": Permission.WALLET_ADJUST,
    "wallet_take": Permission.WALLET_ADJUST,
    # their services
    "subs": Permission.SUBSCRIPTIONS_READ,
    "sub": Permission.SUBSCRIPTIONS_READ,
    "sub_extend": Permission.SUBSCRIPTIONS_WRITE,
    "sub_traffic": Permission.SUBSCRIPTIONS_WRITE,
    "sub_suspend": Permission.SUBSCRIPTIONS_WRITE,
    "sub_revoke": Permission.SUBSCRIPTIONS_WRITE,
    "sub_resume": Permission.SUBSCRIPTIONS_WRITE,
    # orders
    "orders": Permission.ORDERS_READ,
    "order": Permission.ORDERS_READ,
    "retry": Permission.SUBSCRIPTIONS_WRITE,
    # numbers
    "stats": Permission.ANALYTICS_VIEW,
    "top": Permission.ANALYTICS_VIEW,
    "top_list": Permission.ANALYTICS_VIEW,
    "export": Permission.ANALYTICS_EXPORT,
    # staff
    "admins": Permission.ADMINS_READ,
    "add_admin": Permission.ADMINS_WRITE,
    "role": Permission.ADMINS_WRITE,
    # the database itself; the handler also requires a super admin
    "backup": Permission.SETTINGS_WRITE,
    # the bot's own texts and buttons
    "texts": Permission.SETTINGS_WRITE,
    "text": Permission.SETTINGS_WRITE,
    "text_edit": Permission.SETTINGS_WRITE,
    "text_reset": Permission.SETTINGS_WRITE,
    "rules_toggle": Permission.SETTINGS_WRITE,
    "menu_buttons": Permission.SETTINGS_WRITE,
    "menu_btn": Permission.SETTINGS_WRITE,
    "tutorials": Permission.SETTINGS_WRITE,
    "tutorial": Permission.SETTINGS_WRITE,
    "tutorial_rm": Permission.SETTINGS_WRITE,
    # a message pinned in every customer's chat
    "pin": Permission.BROADCAST_SEND,
    "pin_go": Permission.BROADCAST_SEND,
    "unpin": Permission.BROADCAST_SEND,
}

#: The FSM state an operator conversation is in, by its aiogram name.
STATE_PERMISSIONS: dict[str, Permission | None] = {
    "AdminFlow:rejecting_payment": Permission.PAYMENTS_APPROVE,
    "AdminFlow:replying_to_ticket": Permission.TICKETS_REPLY,
    "AdminFlow:adding_admin_id": Permission.ADMINS_WRITE,
    "AdminFlow:finding_customer": Permission.USERS_READ,
    "AdminFlow:wallet_amount": Permission.WALLET_ADJUST,
    "AdminFlow:wallet_reason": Permission.WALLET_ADJUST,
    "AdminFlow:messaging_customer": Permission.USERS_WRITE,
    "AdminFlow:suspending_customer": Permission.USERS_SUSPEND,
    "AdminFlow:subscription_days": Permission.SUBSCRIPTIONS_WRITE,
    "AdminFlow:subscription_gib": Permission.SUBSCRIPTIONS_WRITE,
    "AdminFlow:subscription_reason": Permission.SUBSCRIPTIONS_WRITE,
    "PinFlow:composing": Permission.BROADCAST_SEND,
    "TextFlow:writing": Permission.SETTINGS_WRITE,
    "TextFlow:tutorial": Permission.SETTINGS_WRITE,
}

#: Returned for an action or state nobody declared: refused, never assumed.
_UNDECLARED = object()


def required_permission(*, action: str | None = None, state: str | None = None) -> Any:
    """The permission for a button or a conversation step; `_UNDECLARED` if none is set."""
    if action is not None:
        return ACTION_PERMISSIONS.get(action, _UNDECLARED)
    if state is not None:
        return STATE_PERMISSIONS.get(state, _UNDECLARED)
    return None


async def current_staff(scope: Any, user: Any) -> Admin | None:
    """The staff account behind this Telegram user, or None.

    A reseller has an admin account too - it is how they reach their own
    area - and is not staff. A suspended or locked account loses the bot at
    the same moment it loses the panel.
    """
    if user is None or scope is None:
        return None
    admin: Admin | None = await scope.admins.get_by_telegram_id(user.telegram_id)
    if admin is None or not admin.status.can_authenticate:
        return None
    if admin.role is AdminRole.RESELLER:
        return None
    return admin


# Looked up through the module so tests can stand in for the database.
_current_staff = current_staff


class AdminAccess(BaseMiddleware):
    """Refuses an operator call the caller's role does not cover."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        permission: Any = None
        callback_data = data.get("callback_data")
        if isinstance(callback_data, AdminCB):
            permission = required_permission(action=callback_data.action)
        else:
            raw_state = data.get("raw_state")
            if isinstance(raw_state, str) and raw_state in STATE_PERMISSIONS:
                permission = required_permission(state=raw_state)

        if permission is None:
            return await handler(event, data)

        admin = await _current_staff(data.get("scope"), data.get("user"))
        if admin is not None and permission is not _UNDECLARED and admin.has_permission(permission):
            return await handler(event, data)

        logger.info(
            "bot.admin.refused",
            action=getattr(callback_data, "action", None),
            state=data.get("raw_state"),
            role=getattr(getattr(admin, "role", None), "value", None),
        )
        await _refuse(event, data)
        return None


async def _refuse(event: TelegramObject, data: dict[str, Any]) -> None:
    text = A.NO_PERMISSION if data.get("user") is not None else A.NOT_AN_ADMIN
    if isinstance(event, Message):
        # Out of the conversation, or the next message would be refused too.
        state = data.get("state")
        if state is not None:
            await state.clear()
        await event.answer(text)
        return
    # A callback: an alert, so the refusal is not mistaken for a slow button.
    await cast(CallbackQuery, event).answer(text, show_alert=True)


__all__ = [
    "ACTION_PERMISSIONS",
    "STATE_PERMISSIONS",
    "AdminAccess",
    "current_staff",
    "required_permission",
]
