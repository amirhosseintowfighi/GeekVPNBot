"""A message to a reseller's customer goes out through the reseller's bot.

Telegram will not let a bot open a conversation the person never started. A
reseller's customer has spoken to the reseller's bot and never to ours, so
every delivery link, expiry warning and payment approval sent from our token
was refused.

It failed silently, which is the part that matters: a refusal is recorded as a
suppression, and a suppression looks exactly like a customer who blocked us. So
the platform's own logs would have shown a shop full of people who had all
blocked the bot on the same day, and nobody would have read it that way.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.unit

SYNC_SCOPE = pathlib.Path("src/geekvpn/infrastructure/di/sync_scope.py")


class Row:
    def __init__(self, token: str | None) -> None:
        self.bot_token_encrypted = token


class Session:
    def __init__(self, row: Row | None) -> None:
        self._row = row

    def get(self, _model: Any, _key: Any) -> Any:
        return self._row


class Settings:
    class telegram:
        class bot_token:
            @staticmethod
            def get_secret_value() -> str:
                return "platform-token"


class Container:
    settings = Settings()


def _scope(reseller_id: uuid.UUID | None, row: Row | None):
    from geekvpn.infrastructure.di.sync_scope import SyncScope

    return SyncScope(container=Container(), session=Session(row), reseller_id=reseller_id)


def test_our_own_shop_speaks_with_our_own_bot():
    assert _scope(None, None)._bot_token() == "platform-token"


def test_a_resellers_shop_speaks_with_theirs():
    scope = _scope(uuid.uuid4(), Row("reseller-token"))

    assert scope._bot_token() == "reseller-token"


def test_a_reseller_with_no_bot_does_not_borrow_ours():
    """No fallback, deliberately.

    Sending from the wrong bot does not merely fail - it fails in a way that
    reads as the customer's fault. An empty answer disables the Telegram
    channel and leaves the Mini App inbox, which is honest.
    """
    scope = _scope(uuid.uuid4(), Row(None))

    assert scope._bot_token() == ""


def test_a_reseller_whose_row_is_gone_does_not_borrow_ours_either():
    assert _scope(uuid.uuid4(), None)._bot_token() == ""


def test_the_channel_asks_which_shop_rather_than_the_settings():
    """The whole bug was one attribute read.

    `channels` took the platform token straight from settings, which is correct
    for exactly one shop out of every shop there is.
    """
    tree = ast.parse(SYNC_SCOPE.read_text(encoding="utf-8"))
    channels = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "channels"
    )
    source = ast.unparse(channels)

    assert "_bot_token()" in source
    assert "settings.telegram.bot_token" not in source
