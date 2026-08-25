"""Answering a support message by replying to it.

The ticket is identified from the text being replied to, not from a stored
message id. Telegram hands the bot the quoted message in full and the reference
is already printed in it, so nothing has to be remembered between the process
that sent the answer and the process that receives the reply.

That makes the reference the whole security boundary, which is why it is
resolved against the sender's own tickets and never searched globally: a quote
can be forged, and a forged one must find nothing.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.handlers.support import REFERENCE

pytestmark = pytest.mark.unit


def test_a_reference_is_found_in_the_message_the_bot_sends() -> None:
    from geekvpn.domain.notifications.message import render

    body = render(
        "ticket.answered", reference="SUP-1405-000042", body="سرور عوض شد"
    ).body_fa

    found = REFERENCE.search(body)
    assert found is not None
    assert found.group(0) == "SUP-1405-000042"


def test_an_ordinary_message_carries_none() -> None:
    """A reply to something else must fall through, not open a ticket."""
    assert REFERENCE.search("سلام، سرویس من کار نمی‌کند") is None


def test_a_reference_shaped_like_ours_but_not_ours_is_still_only_a_hint() -> None:
    """It matches, and then resolves against the sender's own tickets.

    Worth stating: the pattern is deliberately permissive, and the check that
    matters happens afterwards.
    """
    assert REFERENCE.search("SUP-1400-000001") is not None


def test_the_year_and_sequence_widths_match_what_is_printed() -> None:
    from geekvpn.domain.support.ticket import format_ticket_reference

    printed = format_ticket_reference(year=1405, sequence=7)

    assert REFERENCE.fullmatch(printed) is not None


def test_a_reply_handler_exists_before_the_flow_handlers() -> None:
    """Someone mid-flow who replies to an older support message means the
    reply, not the flow - so the reply handler has to be registered first."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "geekvpn"
        / "presentation"
        / "bot"
        / "handlers"
        / "support.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)
    order = [
        node.name
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    ]

    assert order.index("on_reply_to_support") < order.index("on_ticket_reply_text")
