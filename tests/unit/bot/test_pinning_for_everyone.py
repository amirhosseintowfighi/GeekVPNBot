"""One announcement, copied and pinned in every customer's chat; and undone."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.presentation.bot.handlers import admin_pin

pytestmark = pytest.mark.unit


class Cache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class Bot:
    def __init__(self, blocked: set[int]) -> None:
        self.blocked = blocked
        self.pinned: list[tuple[int, int]] = []
        self.unpinned: list[tuple[int, int]] = []
        self.said: list[tuple[int, str]] = []

    async def copy_message(self, *, chat_id: int, from_chat_id: int, message_id: int) -> Any:
        if chat_id in self.blocked:
            raise RuntimeError("bot was blocked by the user")
        return SimpleNamespace(message_id=1000 + chat_id)

    async def pin_chat_message(self, *, chat_id: int, message_id: int, **_: Any) -> None:
        self.pinned.append((chat_id, message_id))

    async def unpin_chat_message(self, *, chat_id: int, message_id: int) -> None:
        self.unpinned.append((chat_id, message_id))

    async def send_message(self, chat_id: int, text: str, **_: Any) -> None:
        self.said.append((chat_id, text))


async def test_each_reachable_customer_gets_it_pinned_and_it_is_remembered() -> None:
    cache = Cache()
    cache.values[admin_pin.RUNNING_KEY] = "1"
    bot = Bot(blocked={2})
    container = SimpleNamespace(cache=cache)

    await admin_pin._pin_everywhere(bot, container, [1, 2, 3], 99, 5, report_to=99)  # type: ignore[arg-type]

    assert bot.pinned == [(1, 1001), (3, 1003)]
    assert json.loads(cache.values[admin_pin.PINNED_KEY]) == {"1": 1001, "3": 1003}
    # The lock is released and the operator is told how it went.
    assert admin_pin.RUNNING_KEY not in cache.values
    assert bot.said and bot.said[-1][0] == 99


async def test_taking_it_down_unpins_exactly_what_was_pinned() -> None:
    cache = Cache()
    bot = Bot(blocked=set())

    await admin_pin._unpin_everywhere(  # type: ignore[arg-type]
        bot, SimpleNamespace(cache=cache), {"1": 1001, "3": 1003}, report_to=99
    )

    assert bot.unpinned == [(1, 1001), (3, 1003)]
