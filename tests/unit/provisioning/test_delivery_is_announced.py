"""Provisioning must tell somebody the service exists.

The handler was written and subscribed, and the message still never arrived,
because the event never reached the subscription. `ProvisioningService` runs on
the async side and was given a logging-only publisher; the dispatch table that
carries notifications lives in the synchronous scope, on another session. A
synchronous `publish_all` from there could not reach it and was never going to.

So the announcement crosses explicitly, from the one function every delivery
passes through - the bot's checkout, an operator's retry, and the worker
draining a stuck order all end up in `provision`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3] / "src" / "geekvpn"
SERVICE = ROOT / "application" / "provisioning" / "provisioning_service.py"
SCOPE = ROOT / "infrastructure" / "di" / "scope.py"


def _function(path: Path, name: str) -> str:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{path.name}:{name} is gone")


def test_provision_announces_before_it_returns() -> None:
    source = _function(SERVICE, "provision")

    assert "_announce" in source, (
        "nothing tells the customer their service exists; the events go to a "
        "publisher that only logs"
    )


def test_the_announcement_cannot_fail_the_delivery() -> None:
    """The account is created and the money is ours by this point.

    Failing the provision over a notification would turn a delivered service
    into a failed order, and the retry would ask the panel for a second
    account.
    """
    source = _function(SERVICE, "_announce")

    assert "try:" in source and "except" in source


def test_only_activation_is_announced() -> None:
    """A renewal is a different message, and an order event is not one at all."""
    source = _function(SERVICE, "_announce")

    assert "SubscriptionActivated" in source


def test_the_scope_crosses_into_the_synchronous_side() -> None:
    """Where the notification engine and its dispatch table actually live."""
    source = _function(SCOPE, "_announce_delivery")

    assert "build_sync_scope" in source
    assert "run_in_threadpool" in source, (
        "the crossing blocks the event loop; every other crossing in this "
        "codebase goes through a threadpool"
    )


def test_the_service_is_given_the_callback() -> None:
    """A wired handler with no caller is what this whole file is about."""
    source = _function(SCOPE, "provisioning")

    assert "on_activated=self._announce_delivery" in source


def test_a_create_without_a_link_is_read_back_once() -> None:
    """Some panels fill the subscription link in on a read, not on the create.

    Delivering an account with no link is delivering something the customer
    cannot use - and they will not know the difference between that and a
    broken server.
    """
    source = _function(SERVICE, "provision")

    assert "if not account.subscription_url:" in source
    assert "get_account" in source


def test_the_re_read_cannot_fail_the_provision() -> None:
    """An account that exists beats a failed order, every time."""
    source = _function(SERVICE, "provision")
    start = source.index("if not account.subscription_url:")

    assert "except PanelError:" in source[start:]


def test_the_link_travels_with_the_announcement() -> None:
    """Nothing has committed when this fires.

    The subscription row exists only inside the transaction that is still
    open, so a second connection reading it by id finds nothing - which is
    exactly what happened, on every delivery, while the link sat in the row
    the whole time.
    """
    source = _function(SERVICE, "provision")

    assert "subscription.subscription_url" in source
