"""Every user-facing string must survive UTF-8 encoding.

An emoji written as a UTF-16 surrogate pair (`"\\ud83d\\udee1"` instead of
`"\\U0001f6e1"`) is a valid escape in source and a broken string at runtime:
Telegram's client fails to encode it, so the customer gets no message at all,
and nothing flags it until somebody presses that button. It happened to the
bank-gateway screen once.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.ui import text as T

MESSAGES = sorted(
    (name, value) for name, value in vars(T).items() if name.isupper() and isinstance(value, str)
)


@pytest.mark.parametrize(("name", "value"), MESSAGES, ids=[name for name, _ in MESSAGES])
def test_the_message_encodes_as_utf8(name: str, value: str) -> None:
    value.encode("utf-8")
