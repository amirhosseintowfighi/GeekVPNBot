"""Fetching updates ourselves, for when Telegram cannot reach this server.

A server inside Iran loses all inbound international traffic during an
outage, and with it every webhook. Outbound through a SOCKS5 proxy still works,
so the bot asks Telegram for its updates instead (`getUpdates`) - the main bot
and every active reseller's, each in its own loop. Updates go to the same
dispatcher, with the same `reseller_id` and `stickers` values the tenant
webhook passes, so no handler can tell which transport delivered them.

Each loop deletes its bot's webhook first: Telegram refuses `getUpdates` to a
bot with a webhook set. It never drops pending updates in doing so - a switch
to polling during an outage is exactly when customers' messages are queued.

Resellers are re-read every `REFRESH_SECONDS`, so a bot added or suspended
while polling starts or stops without a restart.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Final

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
from aiogram.types import Update

from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

#: Seconds Telegram holds a `getUpdates` open waiting for something to arrive.
LONG_POLL_SECONDS: Final = 25
#: How often the reseller list is re-read.
REFRESH_SECONDS: Final = 60.0
#: Ceiling on the wait between failed attempts. Short enough that a proxy
#: coming back is noticed within a minute.
MAX_BACKOFF_SECONDS: Final = 60.0

TenantSource = Callable[[], Awaitable[dict[uuid.UUID, Bot]]]


class UpdatePoller:
    def __init__(
        self,
        dispatcher: Dispatcher,
        *,
        main_bot: Bot,
        tenants: TenantSource,
        allowed_updates: list[str] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._dispatcher = dispatcher
        self._main_bot = main_bot
        self._tenants = tenants
        self._allowed = allowed_updates
        self._sleep = sleep
        self._loops: dict[uuid.UUID | None, asyncio.Task[None]] = {}
        #: Handlers in flight. Kept so they are not garbage-collected mid-run.
        self._handling: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        """Poll until cancelled."""
        self._start(None, self._main_bot, {})
        try:
            while True:
                await self._refresh()
                await self._sleep(REFRESH_SECONDS)
        finally:
            for task in self._loops.values():
                task.cancel()
            await asyncio.gather(*self._loops.values(), return_exceptions=True)
            self._loops.clear()

    async def _refresh(self) -> None:
        try:
            bots = await self._tenants()
        except Exception:
            # The main bot keeps polling; the resellers are retried next round.
            logger.exception("bot.polling.tenants_unavailable")
            return
        for reseller_id in [key for key in self._loops if key is not None]:
            if reseller_id not in bots:
                self._loops.pop(reseller_id).cancel()
                logger.info("bot.polling.tenant_stopped", reseller=reseller_id.hex)
        for reseller_id, bot in bots.items():
            if reseller_id not in self._loops:
                # The tenant webhook's values, so the reseller's customers get
                # the reseller's shop and not ours.
                self._start(reseller_id, bot, {"reseller_id": reseller_id.hex, "stickers": None})

    def _start(self, key: uuid.UUID | None, bot: Bot, extra: dict[str, Any]) -> None:
        self._loops[key] = asyncio.create_task(self._poll(bot, extra, key))

    async def _poll(self, bot: Bot, extra: dict[str, Any], key: uuid.UUID | None) -> None:
        name = key.hex if key else "main"
        offset: int | None = None
        backoff = 1.0
        webhook_cleared = False
        while True:
            try:
                if not webhook_cleared:
                    await bot.delete_webhook(drop_pending_updates=False)
                    webhook_cleared = True
                    logger.info("bot.polling.started", bot=name)
                updates = await bot.get_updates(
                    offset=offset,
                    timeout=LONG_POLL_SECONDS,
                    allowed_updates=self._allowed,
                    request_timeout=LONG_POLL_SECONDS + 10,
                )
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except TelegramUnauthorizedError:
                # A revoked token will not start working by being asked again;
                # the next refresh drops it once the reseller's row says so.
                logger.warning("bot.polling.unauthorized", bot=name)
                return
            except TelegramConflictError:
                # Someone set a webhook again, or a second poller is running.
                logger.warning("bot.polling.conflict", bot=name)
                webhook_cleared = False
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
            except Exception as failure:
                # The proxy down, Telegram slow: the usual state of an outage.
                logger.warning("bot.polling.failed", bot=name, error=type(failure).__name__)
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            for update in updates:
                offset = update.update_id + 1
                # Each update on its own task, as a webhook would be: one slow
                # handler must not hold up every other customer's message.
                task = asyncio.create_task(self._handle(bot, update, extra))
                self._handling.add(task)
                task.add_done_callback(self._handling.discard)

    async def _handle(self, bot: Bot, update: Update, extra: dict[str, Any]) -> None:
        try:
            await self._dispatcher.feed_update(bot=bot, update=update, **extra)
        except Exception:
            logger.exception("bot.update_failed", update_id=update.update_id)


__all__ = ["LONG_POLL_SECONDS", "REFRESH_SECONDS", "UpdatePoller"]
