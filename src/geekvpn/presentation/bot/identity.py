"""Bot-side identity middleware.

Every Telegram update arrives already proven authentic - the webhook secret
token was checked before the update was parsed. So the bot does not verify a
signature; it resolves the update's Telegram id to a `User`, creating one on
first contact, and injects it into the handler's data.

The middleware owns a transaction per update. A handler that raises leaves no
half-written row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TelegramUser

from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.ports.telegram_auth import TelegramIdentity
from geekvpn.domain.identity.enums import AuthMethod
from geekvpn.domain.identity.errors import AccountSuspendedError
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger("bot.identity")

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class IdentityMiddleware(BaseMiddleware):
    """Injects `user` (domain `User`) and `scope` into handler data."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        telegram_user = _extract_user(event)
        if telegram_user is None or telegram_user.is_bot:
            # Channel posts and bot-authored updates have no customer behind
            # them; pass them through unauthenticated.
            return await handler(event, data)

        async with self._container.unit_of_work() as uow:
            scope = build_scope(self._container, uow.session)
            identity = TelegramIdentity(
                telegram_id=telegram_user.id,
                method=AuthMethod.TELEGRAM_BOT,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                language_code=telegram_user.language_code,
                is_premium=bool(telegram_user.is_premium),
                start_param=_extract_start_param(event),
            )
            try:
                result = await scope.authenticate_telegram.from_trusted_bot_update(
                    identity, context=RequestContext(device_label="telegram-bot")
                )
            except AccountSuspendedError:
                logger.warning("bot.identity.suspended", telegram_id=telegram_user.id)
                await uow.commit()
                data["user"] = None
                data["suspended"] = True
                return await handler(event, data)

            data["scope"] = scope
            data["user"] = result.user
            data["is_new_user"] = result.is_new_user
            outcome = await handler(event, data)
            await uow.commit()
            return outcome


def _extract_user(event: TelegramObject) -> TelegramUser | None:
    if not isinstance(event, Update):
        return None
    return event.event_from_user


def _extract_start_param(event: TelegramObject) -> str | None:
    """Pull `ref_XXXX` out of a `/start ref_XXXX` deep link."""
    if not isinstance(event, Update) or event.message is None:
        return None
    text = event.message.text or ""
    if not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None
