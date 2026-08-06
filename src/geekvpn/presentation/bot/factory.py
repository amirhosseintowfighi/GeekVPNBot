"""Aiogram 3 bot and dispatcher factories.

Webhook only - polling does not survive more than one replica and is not a
production transport.

FSM state lives in Redis, not memory, for the same reason: a restart or a
second replica must not lose a user mid-flow.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from geekvpn.infrastructure.config.settings import Settings
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.bot.handlers import (
    dashboard,
    fallback,
    faq,
    menu,
    profile,
    purchase,
    referral,
    renewal,
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
from geekvpn.presentation.bot.services import BotServices
from geekvpn.presentation.bot.throttle import ThrottlingMiddleware

#: Registration order matters. Aiogram walks routers in order and stops at the
#: first handler whose filters match, so anything with broad filters must come
#: last. `fallback` matches essentially everything, which is exactly why it is
#: the final entry and must stay there.
ROUTERS = (
    system,
    start,
    menu,
    shop,
    purchase,
    dashboard,
    renewal,
    wallet,
    referral,
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
    services: BotServices | None = None,
) -> Dispatcher:
    """Build the dispatcher.

    `services` is registered as workflow data, so aiogram injects it by name
    into every handler that declares a `services: BotServices` parameter.
    Handlers therefore never touch the container, which is what makes them
    callable directly from a test with a bundle of fakes.

    It is optional so that a caller which only needs the wiring - a smoke
    test asserting the router order, for instance - does not have to build
    eight adapters first.
    """
    dispatcher = Dispatcher(
        storage=RedisStorage(redis=container.redis),
        settings=settings,
        container=container,
        services=services,
    )

    # Applied to every update type, before any handler runs. Order is the
    # order of registration: correlate, then log, then resolve identity - so
    # an identity failure is already correlated and logged. Throttling comes
    # last of the four because a rejected update should still be traceable.
    for observer in (dispatcher.update,):
        observer.outer_middleware(CorrelationIdMiddleware())
        observer.outer_middleware(LoggingMiddleware())
        observer.outer_middleware(IdentityMiddleware(container))
        observer.outer_middleware(ThrottlingMiddleware())

    for module in ROUTERS:
        dispatcher.include_router(module.router)

    return dispatcher
