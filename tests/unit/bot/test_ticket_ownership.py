"""A ticket id in a callback is an assertion, not a fact.

Every route into a thread carries a reference or an id through a Telegram
message, which anyone can craft. So both reads check the ticket belongs to the
sender, and the reference lookup only ever searches that customer's own list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

READERS = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "geekvpn"
    / "infrastructure"
    / "bot"
    / "sync_readers.py"
)


def _source(name: str) -> str:
    tree = ast.parse(READERS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name} is gone from the ticket reader")


@pytest.mark.parametrize("method", ["thread", "reply"])
def test_it_checks_the_ticket_belongs_to_the_caller(method: str) -> None:
    source = _source(method)

    assert "user_id != telegram_id" in source, (
        f"{method} trusts a ticket id that arrived through a Telegram message"
    )


def test_the_reference_lookup_searches_only_this_customers_tickets() -> None:
    """A global search would turn a printed reference into a way to read
    somebody else's conversation."""
    source = _source("find_by_reference")

    assert "list_for_user" in source
    assert "get_ticket" not in source


def test_the_thread_excludes_internal_notes() -> None:
    """Notes are written for colleagues, about the customer."""
    source = _source("thread")

    assert "include_internal" not in source, (
        "internal notes are excluded by default; asking for them here would "
        "put an agent's private note in front of the person it is about"
    )
