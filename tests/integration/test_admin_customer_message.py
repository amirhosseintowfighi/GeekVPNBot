"""Writing to one customer from the admin panel.

The panel could suspend a customer, read their wallet and adjust it, but there
was no way to say anything to them - the only outbound path was a broadcast to
an audience, which is the wrong tool for answering one person.

These pin the three decisions that are easy to get wrong later.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.api.app import create_app

pytestmark = pytest.mark.integration

ROUTER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "geekvpn"
    / "presentation"
    / "api"
    / "routers"
    / "admin_customers.py"
)

PATH = "/api/v1/admin/customers/{customer_id}/message"


def _endpoint_source() -> str:
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "message_customer":
            return ast.unparse(node)
    raise AssertionError("the direct-message endpoint is gone")


def test_the_route_is_registered() -> None:
    """Unreachable code is this project's recurring failure, so it is checked."""
    assert PATH in create_app().openapi()["paths"]


def test_it_is_gated_on_the_permission_that_sends_messages() -> None:
    source = _endpoint_source()

    assert f"Permission.{Permission.BROADCAST_SEND.name}" in source


def test_it_is_sent_as_critical_so_a_preference_cannot_silence_it() -> None:
    """An operator writing to a named customer is answering them.

    Any other category can be switched off in the customer's notification
    settings, which would leave the operator believing they had replied.
    """
    source = _endpoint_source()

    assert "NotificationCategory.CRITICAL" in source


def test_it_goes_through_the_engine_rather_than_the_bot_directly() -> None:
    """So it is recorded, deduped and visible to the next operator."""
    source = _endpoint_source()

    assert "engine.dispatch" in source
