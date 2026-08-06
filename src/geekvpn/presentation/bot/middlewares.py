"""Aiogram middlewares mirroring the HTTP ones.

A Telegram update gets the same correlation id treatment as an HTTP request so
a user's journey is traceable across both surfaces.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from geekvpn.infrastructure.logging.context import bind_correlation_id, reset_correlation_id
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger("bot.update")

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class CorrelationIdMiddleware(BaseMiddleware):
    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        token = bind_correlation_id()
        try:
            return await handler(event, data)
        finally:
            reset_correlation_id(token)


class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        started = time.perf_counter()
        update_id = event.update_id if isinstance(event, Update) else None
        try:
            result = await handler(event, data)
        except Exception:
            logger.exception("bot.update.failed", update_id=update_id)
            raise
        logger.info(
            "bot.update",
            update_id=update_id,
            event_type=type(event).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return result
