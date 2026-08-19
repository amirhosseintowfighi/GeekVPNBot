"""Bot service: a small ASGI app that receives Telegram webhooks.

The bot runs as its own process (own container, own scaling profile) but is
built from the same image and the same container as the API.

Security: Telegram signs every webhook call with the secret token supplied at
registration time. Any request without the exact header is rejected before the
update is parsed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Protocol

from aiogram import Bot
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from geekvpn import __version__
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

        if settings.telegram.set_webhook_on_startup:
            await register_webhook(
                app.state.bot,
                settings,
                allowed_updates=app.state.dispatcher.resolve_used_update_types(),
            )

        logger.info("bot.startup", env=settings.app.env.value)
        try:
            yield
        finally:
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
