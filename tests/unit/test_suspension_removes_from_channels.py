"""A suspended customer can be taken out of the shop's required channels."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from geekvpn.application.platform.channel_gate import RequiredChannel
from geekvpn.infrastructure.di import scope as scope_module
from geekvpn.infrastructure.di.scope import RequestScope

pytestmark = pytest.mark.unit


class Sender:
    banned: ClassVar[list[tuple[str, int]]] = []

    def __init__(self, token: str) -> None:
        self.token = token

    def ban_chat_member(self, *, chat: str, user_id: int) -> None:
        if chat == "@broken":
            raise RuntimeError("bot is not an admin there")
        Sender.banned.append((chat, user_id))


def build(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> Any:
    Sender.banned = []
    monkeypatch.setattr(scope_module, "HttpOperatorSender", Sender)
    container = SimpleNamespace(
        settings=SimpleNamespace(
            telegram=SimpleNamespace(bot_token=SimpleNamespace(get_secret_value=lambda: "t"))
        )
    )
    request = RequestScope(container=container, session=object())  # type: ignore[arg-type]

    async def get(definition: Any) -> bool:
        return enabled

    async def active() -> list[RequiredChannel]:
        return [
            RequiredChannel(id="1", chat_ref="@geekvpn", title_fa="a"),
            RequiredChannel(id="2", chat_ref="@broken", title_fa="b"),
        ]

    request.__dict__["settings_service"] = SimpleNamespace(get=get)
    request.__dict__["required_channels"] = SimpleNamespace(active=active)
    return request


async def test_switched_on_it_bans_from_every_channel_it_can(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed = await build(monkeypatch, enabled=True).remove_from_channels(42)

    # The channel that refused is skipped; the suspension already stands.
    assert removed == 1
    assert Sender.banned == [("@geekvpn", 42)]


async def test_switched_off_it_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await build(monkeypatch, enabled=False).remove_from_channels(42) == 0
    assert Sender.banned == []
