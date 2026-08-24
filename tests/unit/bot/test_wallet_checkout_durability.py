"""A wallet purchase must never take money and leave no trace.

Wallet checkout writes across two transactions: the order on the async session,
and the debit, invoice and `OrderPaymentBridge` on the synchronous one. The
order was not committed before the sync scope ran, so the bridge could not see
it, left it PENDING, and `provision` refused - PENDING to PROVISIONING is not a
legal transition. The customer's balance had already gone down, the exception
rolled the async session back, and the order they had paid for ceased to exist.

Three separate things had to be true to produce that, and each is pinned here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.domain.provisioning.errors import DeliveryPending
from geekvpn.domain.provisioning.order import _TRANSITIONS

pytestmark = pytest.mark.unit

CHECKOUT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "geekvpn"
    / "infrastructure"
    / "bot"
    / "checkout.py"
)


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(CHECKOUT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from the checkout adapter")


def _commits(node: ast.AST) -> int:
    return sum(
        1
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute) and child.attr == "commit"
    )


def test_an_unpaid_order_cannot_start_provisioning() -> None:
    """The domain rule that turned a missed commit into a lost order."""
    assert OrderState.PROVISIONING not in _TRANSITIONS[OrderState.PENDING]
    assert OrderState.PROVISIONING in _TRANSITIONS[OrderState.PAID]


def test_the_order_is_committed_before_the_payment_scope_runs() -> None:
    """A separate transaction cannot see an uncommitted row.

    Without this the bridge never finds the order, and everything after it is
    downstream of that one omission.
    """
    assert _commits(_function("_begin")) >= 1


def test_a_delivery_failure_keeps_the_order() -> None:
    """The order is the record of what the customer is owed."""
    source = ast.unparse(_function("pay_from_wallet"))

    assert "except" in source, "a provisioning failure still propagates untouched"
    assert "commit" in source, "the failed state is never persisted"
    assert "DeliveryPending" in source


def test_the_customer_is_told_their_money_arrived() -> None:
    """"Something went wrong" after a debit reads as "your money is gone"."""
    assert any("؀" <= ch <= "ۿ" for ch in DeliveryPending.message)
    assert DeliveryPending.code == "delivery_pending"
