"""A ticket row must exist before a message points at it.

`support_messages.ticket_id` is a foreign key to `support_tickets.id`, and the
two models carry no `relationship()` - so nothing tells SQLAlchemy which insert
has to come first. It emitted the message first and Postgres refused it:

    ForeignKeyViolation: Key (ticket_id)=(...) is not present in table
    "support_tickets"

Which meant a *new* ticket could never be saved, while a reply to an existing
one was fine, because that parent row was already there. It went unnoticed
because the reference bug in front of it meant no ticket ever reached this code
at all.

The models are Postgres-specific (JSONB), so this cannot be exercised against
SQLite. What is checked instead is the ordering itself, in both repositories,
because that is the whole of the fix.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPOSITORIES = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "geekvpn"
    / "infrastructure"
    / "persistence"
    / "repositories"
)

#: (file, function) pairs that write a ticket and its messages together.
WRITERS = (
    ("sync_support.py", "save"),
    ("support.py", "add"),
)


def _statements(filename: str, function: str) -> list[str]:
    tree = ast.parse((REPOSITORIES / filename).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == function:
            return [ast.unparse(statement) for statement in ast.walk(node)]
    raise AssertionError(f"{filename}:{function} is gone")


@pytest.mark.parametrize(("filename", "function"), WRITERS)
def test_the_ticket_is_flushed_before_a_message_references_it(
    filename: str, function: str
) -> None:
    unparsed = "\n".join(_statements(filename, function))

    ticket_added = unparsed.index("ticket_to_row(ticket)")
    flushed = unparsed.index("flush()", ticket_added)
    message_added = unparsed.index("message_to_row(message)")

    assert ticket_added < flushed < message_added, (
        "the message insert can reach the database before the ticket it points "
        "at, which Postgres refuses"
    )


@pytest.mark.parametrize(("filename", "function"), WRITERS)
def test_the_messages_are_flushed_too(filename: str, function: str) -> None:
    """The parent flush must not become the only one."""
    unparsed = "\n".join(_statements(filename, function))
    message_added = unparsed.index("message_to_row(message)")

    assert "flush()" in unparsed[message_added:]
