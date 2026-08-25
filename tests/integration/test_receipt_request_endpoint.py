"""The Mini App asks the bot to collect a receipt, and says which payment for.

Both halves matter. Without the prompt the customer lands in a chat that has
said nothing to them; without the recorded intent the bot has to guess, and it
refuses to guess when two payments are waiting - which is exactly the case a
customer with two unpaid orders is in.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from geekvpn.application.payments.receipt_intent import (
    RECEIPT_REQUESTED_TEMPLATE,
    receipt_intent_key,
)
from geekvpn.domain.notifications.enums import NotificationCategory
from geekvpn.domain.notifications.message import CATALOG
from geekvpn.presentation.api.app import create_app

pytestmark = pytest.mark.integration

ROUTER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "geekvpn"
    / "presentation"
    / "api"
    / "routers"
    / "miniapp.py"
)

PATH = "/api/miniapp/payments/{payment_id}/receipt-request"


def _endpoint_source() -> str:
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "request_receipt":
            return ast.unparse(node)
    raise AssertionError("the receipt-request endpoint is gone")


def test_the_route_is_registered() -> None:
    assert PATH in create_app().openapi()["paths"]


def test_the_intent_is_written_before_the_prompt_is_sent() -> None:
    """The customer can reply faster than we can lose the race.

    Send first and a fast reply arrives while the bot still has nothing
    recorded - back to guessing, in the one case guessing is refused.
    """
    source = _endpoint_source()
    stored = source.index("receipt_intent_key")
    sent = source.index("mutate_scope")

    assert stored < sent, "the prompt goes out before the intent is recorded"


def test_the_key_comes_from_the_shared_helper() -> None:
    """Written twice, the two sides disagree the first time one is edited."""
    assert "receipt_intent_key" in _endpoint_source()
    assert receipt_intent_key(1) != receipt_intent_key(2)


def test_the_prompt_cannot_be_switched_off_by_a_preference() -> None:
    """It was asked for seconds ago. Silence here reads as a broken bot."""
    template = CATALOG[RECEIPT_REQUESTED_TEMPLATE]

    assert template.category is NotificationCategory.CRITICAL


def test_the_prompt_names_the_amount() -> None:
    """Two open payments is the case this exists for; the customer has to be
    able to tell which chat message is about which."""
    assert "amount" in CATALOG[RECEIPT_REQUESTED_TEMPLATE].required_fields()
