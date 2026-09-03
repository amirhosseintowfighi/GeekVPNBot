"""Aiogram 3 bot and dispatcher factories.

Webhook only - polling does not survive more than one replica and is not a
production transport.

FSM state lives in Redis, not memory, for the same reason: a restart or a
second replica must not lose a user mid-flow.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from geekvpn.infrastructure.config.settings import Settings
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.bot.channel_gate import ChannelGateMiddleware
from geekvpn.presentation.bot.handlers import (
    admin,
    dashboard,
    errors,
    fallback,
    faq,
    menu,
    profile,
    purchase,
    referral,
    renewal,
    reseller,
    server_status,
    shop,
    start,
    support,
    system,
    wallet,
)
from geekvpn.presentation.bot.handlers import (
    settings as settings_handlers,
)
from geekvpn.presentation.bot.identity import IdentityMiddleware
from geekvpn.presentation.bot.middlewares import (
    CorrelationIdMiddleware,
    LoggingMiddleware,
)
from geekvpn.presentation.bot.throttle import ThrottlingMiddleware
from geekvpn.presentation.bot.ui.stickers import StickerBook

#: Registration order matters. Aiogram walks routers in order and stops at the
#: first handler whose filters match, so anything with broad filters must come
#: last. `fallback` matches essentially everything, which is exactly why it is
#: the final entry and must stay there.
ROUTERS = (
    errors,
    system,
    admin,
    start,
    menu,
    shop,
    purchase,
    dashboard,
    renewal,
    wallet,
    referral,
    reseller,
    support,
    profile,
    settings_handlers,
    faq,
    server_status,
    fallback,
)


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.telegram.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode(settings.telegram.parse_mode)),
    )


def create_dispatcher(
    settings: Settings,
    container: Container,
    *,
    fetch_receipt: Callable[[str], Awaitable[bytes]] | None = None,
) -> Dispatcher:
    """Build the dispatcher.

    `services` used to be a parameter here and could never have worked: the
    bundle needs a database session, and a dispatcher is built once per
    process. `IdentityMiddleware` builds it per update instead and injects it
    as workflow data, so aiogram still hands every handler its
    `services: BotServices` argument by name.

    `fetch_receipt` is threaded through to the checkout adapter, which needs
    the receipt's bytes - not its Telegram file id - to fingerprint it.
    """
    dispatcher = Dispatcher(
        storage=RedisStorage(redis=container.redis),
        settings=settings,
        container=container,
    )

    # Applied to every update type, before any handler runs. Order is the
    # order of registration: correlate, then log, then resolve identity - so
    # an identity failure is already correlated and logged. Throttling comes
    # last of the four because a rejected update should still be traceable.
    for observer in (dispatcher.update,):
        observer.outer_middleware(CorrelationIdMiddleware())
        observer.outer_middleware(LoggingMiddleware())
        observer.outer_middleware(IdentityMiddleware(container, fetch_receipt=fetch_receipt))
        observer.outer_middleware(ThrottlingMiddleware())
        # Last: it needs the identity resolved above, and a customer who
        # is hammering the bot should be throttled before we spend a
        # Telegram round trip asking whether they joined anything.
        observer.outer_middleware(ChannelGateMiddleware())

    # Available to every handler as `stickers`, the same way `services`
    # is. Handlers that do not decorate simply never declare it.
    dispatcher["stickers"] = StickerBook(settings.telegram.sticker_set)

    for module in ROUTERS:
        dispatcher.include_router(module.router)

    return dispatcher
