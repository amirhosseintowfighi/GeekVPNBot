"""Bot service: a small ASGI app that receives Telegram webhooks.

The bot runs as its own process (own container, own scaling profile) but is
built from the same image and the same container as the API.

Security: Telegram signs every webhook call with the secret token supplied at
registration time. Any request without the exact header is rejected before the
update is parsed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Protocol

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, Update, WebAppInfo
from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from geekvpn import __version__
from geekvpn.application.resellers.tenant_bots import tenant_secret
from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.infrastructure.di.container import Container, build_container, close_container
from geekvpn.infrastructure.health.probes import run_probes
from geekvpn.infrastructure.logging.setup import configure_logging, get_logger
from geekvpn.presentation.api.errors import register_exception_handlers
from geekvpn.presentation.api.middleware import AccessLogMiddleware, CorrelationIdMiddleware
from geekvpn.presentation.api.schemas import (
    DependencyStatus,
    LivenessResponse,
    ReadinessResponse,
)
from geekvpn.presentation.bot.factory import create_bot, create_dispatcher
from geekvpn.presentation.bot.tenants import TenantBots
from geekvpn.presentation.bot.ui import text

logger = get_logger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"  # noqa: S105 - a constant name, not a credential


def _receipt_fetcher(bot: Bot) -> Callable[[str], Awaitable[bytes]]:
    """Download a receipt so it can be fingerprinted from its bytes.

    The digest has to come from the image itself: forwarding a photo yields a
    fresh Telegram file id for identical bytes, so a file-id digest would let
    the same receipt be submitted twice. See `infrastructure/bot/checkout.py`.
    """

    async def fetch(file_id: str) -> bytes:
        buffer = await bot.download(file_id)
        if buffer is None:  # pragma: no cover - only when downloading to disk
            raise RuntimeError("Telegram returned no data for the receipt.")
        return buffer.read()

    return fetch


class SupportsSetWebhook(Protocol):
    async def set_webhook(
        self,
        url: str,
        *,
        secret_token: str,
        drop_pending_updates: bool,
        allowed_updates: list[str],
    ) -> bool: ...


async def register_webhook(
    bot: SupportsSetWebhook,
    settings: Settings,
    *,
    allowed_updates: list[str],
) -> bool:
    """Point Telegram at this deployment. Returns whether it took.

    Failure is logged, never raised. Telegram refuses the call whenever it
    cannot reach the URL over valid TLS, which is the ordinary state of a fresh
    install: the installer starts the bot before certbot has issued anything,
    so the only certificate is the self-signed placeholder. Raising here put
    the container in a restart loop over a condition that resolves itself
    minutes later, and left no bot running to receive the webhook once it did.
    """
    try:
        await bot.set_webhook(
            url=settings.telegram.webhook_url,
            secret_token=settings.telegram.webhook_secret.get_secret_value(),
            drop_pending_updates=False,
            allowed_updates=allowed_updates,
        )
    except Exception as exc:
        # Broad on purpose: aiogram raises its own error for a rejection and the
        # HTTP client raises its own for DNS and TLS. Every one of them means
        # the same thing here - not registered yet, try again later.
        logger.error(
            "bot.webhook.registration_failed",
            url=settings.telegram.webhook_url,
            error=str(exc),
            hint=(
                "Telegram could not reach the webhook URL. Usually DNS does not point "
                "here yet, or TLS is still the self-signed placeholder. Restart the bot "
                "once those are in place."
            ),
        )
        return False

    logger.info("bot.webhook.registered", url=settings.telegram.webhook_url)
    return True


class SupportsSetMenuButton(Protocol):
    async def set_chat_menu_button(self, *, menu_button: MenuButtonWebApp) -> bool: ...


async def register_menu_button(bot: SupportsSetMenuButton, settings: Settings) -> bool:
    """Publish the Mini App as the bot's menu button. Returns whether it took.

    This is the only route a customer has into the Mini App. Nothing in the
    product renders a WebApp button, so until this ran the Mini App was
    reachable only through whatever URL had been typed into BotFather by hand -
    and a wrong one there answers with the API's 404 JSON, which is what
    happened in production: Telegram opened `<api-host>/app/`.

    Failure is logged rather than raised, for the same reason `register_webhook`
    swallows its own: a bot that cannot reach Telegram at boot must still come
    up and serve the updates that arrive once it can.
    """
    url = settings.telegram.mini_app_url
    if not url:
        logger.warning(
            "bot.menu_button.skipped",
            hint=(
                "TELEGRAM__MINI_APP_URL is unset, so the menu button is left as it is. "
                "Customers reach the Mini App through this button and nowhere else."
            ),
        )
        return False

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=text.MENU_BUTTON_MINI_APP,
                web_app=WebAppInfo(url=url),
            )
        )
    except Exception as exc:
        logger.error("bot.menu_button.failed", url=url, error=str(exc))
        return False

    logger.info("bot.menu_button.registered", url=url)
    return True


def create_bot_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        level=settings.logging.level,
        json_output=settings.logging.json,
        redact_keys=settings.logging.redact_keys,
        service=f"{settings.app.name}-bot",
    )
    externally_owned_container = container is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        app.state.settings = settings
        app.state.bot = create_bot(settings)
        app.state.dispatcher = create_dispatcher(
            settings,
            app.state.container,
            fetch_receipt=_receipt_fetcher(app.state.bot),
        )
        # Resellers' own bots. Built lazily per token and cached, because a
        # deployment with thirty resellers would otherwise open thirty HTTP
        # sessions at start-up for bots that may see no traffic all day.
        app.state.tenants = TenantBots(app.state.container, parse_mode=settings.telegram.parse_mode)

        if settings.telegram.set_webhook_on_startup:
            await register_webhook(
                app.state.bot,
                settings,
                allowed_updates=app.state.dispatcher.resolve_used_update_types(),
            )
            await register_menu_button(app.state.bot, settings)

        logger.info("bot.startup", env=settings.app.env.value)
        try:
            yield
        finally:
            await app.state.tenants.close()
            await app.state.bot.session.close()
            if not externally_owned_container:
                await close_container(app.state.container)
            logger.info("bot.shutdown")

    app = FastAPI(
        title="Geek VPN Bot",
        version=__version__,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    @app.post(settings.telegram.webhook_path, include_in_schema=False)
    async def telegram_webhook(
        request: Request,
        secret_token: str = Header(default="", alias=SECRET_HEADER),
    ) -> dict[str, bool]:
        expected = settings.telegram.webhook_secret.get_secret_value()
        if not expected or not compare_digest(secret_token, expected):
            logger.warning("bot.webhook.rejected", reason="bad_secret")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

        update = Update.model_validate(await request.json(), context={"bot": request.app.state.bot})
        # Telegram retries any non-2xx forever, so an exception escaping here
        # turns one handler bug into a redelivery loop hammering every worker.
        # handlers/errors.py catches what handlers raise; this catches what the
        # dispatcher itself raises, which no router can see.
        try:
            await request.app.state.dispatcher.feed_update(bot=request.app.state.bot, update=update)
        except Exception:
            logger.exception("bot.update_failed", update_id=update.update_id)
        return {"ok": True}

    @app.post(settings.telegram.webhook_path + "/r/{tenant}", include_in_schema=False)
    async def tenant_webhook(
        tenant: str,
        request: Request,
        secret_token: str = Header(default="", alias=SECRET_HEADER),
    ) -> dict[str, bool]:
        """One reseller's own bot.

        Serving many bots from one process is only possible because this is
        webhook-driven: polling needs a connection per token, a webhook needs a
        route per token, and a route is free.

        The secret is derived per reseller rather than shared, so a value
        leaked from one reseller's edge cannot authenticate traffic claiming to
        be another. It is compared before the tenant is looked up: an
        unauthenticated caller must not be able to probe which reseller ids
        exist by timing.
        """
        try:
            reseller_id = uuid.UUID(hex=tenant)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None

        platform_secret = settings.telegram.webhook_secret.get_secret_value()
        expected = tenant_secret(platform_secret, reseller_id)
        if not platform_secret or not compare_digest(secret_token, expected):
            logger.warning("bot.tenant_webhook.rejected", reason="bad_secret")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

        bot = await request.app.state.tenants.bot_for(reseller_id)
        if bot is None:
            # A token that was removed, or a reseller who was closed. Telegram
            # retries anything non-2xx forever, so this answers 200 and drops
            # the update rather than building a redelivery loop for a bot that
            # is not coming back.
            logger.info("bot.tenant_webhook.unknown", reseller=tenant)
            return {"ok": True}

        dispatcher = getattr(request.app.state, "reseller_dispatcher", None)
        if dispatcher is None:
            # Deliberately not the platform dispatcher. Feeding a reseller's
            # customer into our own storefront would answer them with our
            # prices, our wallet and our brand, under a name they believe
            # belongs to somebody else - a worse outcome than silence, and one
            # nobody would notice was happening.
            logger.info("bot.tenant_webhook.no_dispatcher", reseller=tenant)
            return {"ok": True}

        update = Update.model_validate(await request.json(), context={"bot": bot})
        try:
            await dispatcher.feed_update(bot=bot, update=update)
        except Exception:
            logger.exception("bot.tenant_update_failed", update_id=update.update_id)
        return {"ok": True}

    @app.get("/health/live", response_model=LivenessResponse)
    async def live() -> LivenessResponse:
        return LivenessResponse(service=f"{settings.app.name}-bot", version=__version__)

    @app.get("/health/ready", response_model=ReadinessResponse)
    async def ready(request: Request, response: Response) -> ReadinessResponse:
        results = await run_probes(request.app.state.container.health_probes)
        healthy = all(r.healthy for r in results)
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="ready" if healthy else "degraded",
            dependencies=[
                DependencyStatus(
                    name=r.name, healthy=r.healthy, latency_ms=r.latency_ms, error=r.error
                )
                for r in results
            ],
        )

    return app
