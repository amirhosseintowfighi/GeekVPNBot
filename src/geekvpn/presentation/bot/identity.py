"""Bot-side identity middleware.

Every Telegram update arrives already proven authentic - the webhook secret
token was checked before the update was parsed. So the bot does not verify a
signature; it resolves the update's Telegram id to a `User`, creating one on
first contact, and injects it into the handler's data.

The middleware owns a transaction per update. A handler that raises leaves no
half-written row.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TelegramUser

from geekvpn.application.identity.dto import RequestContext
from geekvpn.application.ports.telegram_auth import TelegramIdentity
from geekvpn.domain.identity.enums import AuthMethod
from geekvpn.domain.identity.errors import AccountSuspendedError
from geekvpn.infrastructure.bot.services import build_bot_services
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger("bot.identity")

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class IdentityMiddleware(BaseMiddleware):
    """Injects `user`, `scope` and `services` into handler data."""

    def __init__(
        self,
        container: Container,
        *,
        fetch_receipt: Callable[[str], Awaitable[bytes]] | None = None,
    ) -> None:
        self._container = container
        self._fetch_receipt = fetch_receipt

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        telegram_user = _extract_user(event, data)
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
                # Put here by the tenant webhook, from the path the update
                # arrived on. It decides *which* person is being authenticated:
                # the same Telegram account is a separate customer in each
                # reseller's bot, with their own wallet and subscriptions.
                reseller_id=data.get("reseller_id"),
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
            # Which shop this update belongs to, resolved once per update
            # rather than in every handler that needs a price. `None` in the
            # platform's own bot, which is the common case and costs nothing.
            # Set on the scope, not only in the handler data: the storefront
            # and the quoting service are reached from seven places, and a
            # forgotten argument at any of them is a reseller's customer shown
            # our prices - which looks exactly like a working screen.
            scope.reseller = await _shop(scope, data.get("reseller_id"))
            data["reseller"] = scope.reseller
            data["is_new_user"] = result.is_new_user
            # Built here, not in `create_dispatcher`: the bundle needs this
            # update's session, and a dispatcher is constructed once per
            # process. Handlers declare `services: BotServices` and aiogram
            # injects it by name.
            data["services"] = build_bot_services(scope, fetch_receipt=self._fetch_receipt)
            # Shared with the API, which writes a receipt intent here when the
            # Mini App asks the bot to collect one. Handlers that need it
            # declare `cache: Cache`.
            data["cache"] = self._container.cache
            # The operator handlers open their own synchronous scope, the
            # same way the admin API does, because approving a payment and
            # answering a ticket both live on that side of the split.
            data["container"] = self._container
            outcome = await handler(event, data)
            await uow.commit()
            return outcome


async def _shop(scope: Any, reseller_id: Any) -> Any:
    """The reseller behind this update, if it arrived at their bot.

    Failure is `None`, not an exception: a reseller row that cannot be read is
    a shop that falls back to the platform's prices, which is wrong but
    serviceable - and better than a customer who cannot open a menu.
    """
    if not reseller_id:
        return None
    try:
        return await scope.resellers.get(uuid.UUID(hex=str(reseller_id)))
    except Exception:
        logger.warning("bot.identity.shop_unresolved", reseller=str(reseller_id))
        return None


def _extract_user(event: TelegramObject, data: dict[str, Any]) -> TelegramUser | None:
    if not isinstance(event, Update):
        return None
    # From `data`, not from the event. `Update` has no `event_from_user`
    # attribute - aiogram's own UserContextMiddleware resolves the sender and
    # puts it in the handler data, which is where `throttle.py` already reads
    # it from. Reading it off the event with getattr silently returned None for
    # *every* update, so this middleware treated every real customer as an
    # anonymous channel post: no `scope`, no `user`, and no `services` in the
    # data. Every handler that declares `services` then died with a TypeError
    # before running, which is the generic "something went wrong" the bot
    # replied with to every message it ever received.
    sender: TelegramUser | None = data.get("event_from_user")
    return sender


def _extract_start_param(event: TelegramObject) -> str | None:
    """Pull `ref_XXXX` out of a `/start ref_XXXX` deep link."""
    if not isinstance(event, Update) or event.message is None:
        return None
    text = event.message.text or ""
    if not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None
