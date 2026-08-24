"""The buying session must not write over what the paying session decided.

A wallet payment settles inside `checkout.begin`, and `OrderPaymentBridge`
marks the order PAID before that call returns. The bot's session still held the
PENDING copy it had created moments earlier, and `update` applies the whole
aggregate - so linking the invoice afterwards wrote PENDING back over the PAID
the bridge had just committed.

The order then failed `PENDING -> PROVISIONING`, the customer was debited, and
nothing was delivered. Fixing the bridge did not show, because this line undid
the fix a few microseconds later. Two correct-looking writes, one lost update.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

CHECKOUT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "geekvpn"
    / "infrastructure"
    / "bot"
    / "checkout.py"
)


def _begin_source() -> str:
    tree = ast.parse(CHECKOUT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_begin":
            return ast.unparse(node)
    raise AssertionError("_begin is gone from the checkout adapter")


def test_the_order_is_re_read_after_the_payment_scope_runs() -> None:
    """Anything else writes back a copy that is already out of date."""
    source = _begin_source()

    assert "expire_all" in source
    assert "self._order_repository.get(order.id)" in source


def test_the_invoice_link_is_only_written_when_it_is_missing() -> None:
    """The bridge sets it as part of `mark_paid`; a second write is the bug."""
    source = _begin_source()
    index = source.index("order.invoice_id = result.invoice.id")
    guard = source[:index]

    assert "if order.invoice_id is None" in guard, (
        "the invoice link is written unconditionally, which overwrites whatever "
        "the paying scope decided about this order"
    )
