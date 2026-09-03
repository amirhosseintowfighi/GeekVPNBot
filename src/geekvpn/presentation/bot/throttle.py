"""Per-user anti-flood middleware.

Telegram itself rate-limits *us* (30 messages/second overall, ~1/second to a
given chat). A user holding down a button can push us past that and get the
bot temporarily blocked for everyone, so we shed load at the edge instead.

The window is deliberately generous for callback queries: tapping through a
menu quickly is normal behaviour, not abuse. Only sustained hammering trips
it, and the user is told once rather than on every dropped update -- repeated
"slow down" messages are themselves a flood.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from geekvpn.presentation.bot.events import inner_event
from geekvpn.presentation.bot.ui import text as T

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class ThrottlingMiddleware(BaseMiddleware):
    """Token-free sliding minimum-interval throttle.

    State is in-process, not Redis. That is a deliberate trade: a per-update
    Redis round-trip to save a few duplicate taps costs more than it saves,
    and with N replicas the effective limit is simply N x rate, which is
    still bounded.
    """

    def __init__(
        self,
        *,
        message_interval: float = 0.7,
        callback_interval: float = 0.35,
        max_tracked: int = 10_000,
    ) -> None:
        self.message_interval = message_interval
        self.callback_interval = callback_interval
        self.max_tracked = max_tracked
        self._last: OrderedDict[tuple[int, str], float] = OrderedDict()
        self._warned: OrderedDict[int, float] = OrderedDict()

    def _prune(self) -> None:
        while len(self._last) > self.max_tracked:
            self._last.popitem(last=False)
        while len(self._warned) > self.max_tracked:
            self._warned.popitem(last=False)

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # The update, unwrapped. Registered on `dispatcher.update`, this is
        # handed an `Update` - so both branches below missed, every update fell
        # through, and nothing has ever been throttled. See `events.py`.
        inner = inner_event(event)
        if isinstance(inner, CallbackQuery):
            kind, interval = "cb", self.callback_interval
        elif isinstance(inner, Message):
            kind, interval = "msg", self.message_interval
        else:
            return await handler(event, data)

        now = time.monotonic()
        key = (user.id, kind)
        previous = self._last.get(key)

        if previous is not None and now - previous < interval:
            await self._warn(inner, user.id, now)
            return None

        self._last[key] = now
        self._last.move_to_end(key)
        self._prune()
        return await handler(event, data)

    async def _warn(self, event: TelegramObject, user_id: int, now: float) -> None:
        """Tell the user at most once every 5 seconds."""
        last_warned = self._warned.get(user_id)
        if last_warned is not None and now - last_warned < 5.0:
            return
        self._warned[user_id] = now
        self._warned.move_to_end(user_id)
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(T.ERR_RATE_LIMITED, show_alert=False)
            elif isinstance(event, Message):
                await event.answer(T.ERR_RATE_LIMITED)
        except Exception:  # noqa: S110 - see below
            # Warning the user is best-effort; never let it mask the throttle.
            # Telegram rejects an answer to an expired callback, and that must
            # not turn a successful throttle into a handler error.
            pass
