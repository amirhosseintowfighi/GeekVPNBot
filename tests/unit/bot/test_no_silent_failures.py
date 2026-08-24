"""A handler may apologise, but it may not stay quiet.

`on_pay` caught every exception and showed the generic apology without logging
anything. A wallet purchase that debited a customer and delivered nothing
therefore left no traceback, no `handler_failed`, and nothing in the log at
all - so every attempt to diagnose it from outside came back empty, twice, and
the only way to find the cause was to read the code.

Swallowing an exception is sometimes right: the customer should not see a
stack trace, and an apology that raises is worse than the failure. Swallowing
it *silently* never is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

HANDLERS = Path(__file__).resolve().parents[3] / "src" / "geekvpn" / "presentation" / "bot"


def _logs_or_reraises(handler: ast.ExceptHandler) -> bool:
    """Does this `except` leave a trace of what it caught?"""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"exception", "error", "warning"}
        ):
            return True
    return False


def _silent_handlers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    silent: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or _logs_or_reraises(node):
            continue
        # A bare `pass` is a deliberate ignore and reads as one; those carry a
        # comment explaining why, and Telegram refusing an expired callback is
        # the honest example. What this is looking for is an `except` that
        # *does* something - answers the customer - while saying nothing.
        if all(isinstance(child, ast.Pass) for child in node.body):
            continue
        silent.append(f"{path.name}:{node.lineno}")
    return silent


def test_no_money_handler_swallows_a_failure_without_a_word() -> None:
    paths = [
        HANDLERS / "handlers" / "purchase.py",
        HANDLERS / "handlers" / "wallet.py",
    ]
    silent = [entry for path in paths for entry in _silent_handlers(path)]

    assert not silent, (
        "these catch a failure and neither log it nor re-raise, so a customer "
        "can be charged with no record of why it broke:\n  " + "\n  ".join(silent)
    )
