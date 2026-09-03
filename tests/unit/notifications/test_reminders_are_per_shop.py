"""Every customer-facing sweep runs for one shop at a time.

The expiry, traffic and idle sweeps ran once, against a reader that saw every
subscription on the platform, through whichever bot the scope happened to hold.
For a reseller's customer that is our bot - one they have never started - and
Telegram refuses a message from a bot the recipient has not spoken to first.
The refusal is then recorded as a suppression, which reads exactly like a
customer who blocked us.

Structural, because the failure is: a loop that builds one scope is wrong in a
way no assertion about a single send would catch. Same shape as the broadcast
dispatcher's own test, and for the same reason.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

WORKER = pathlib.Path("src/geekvpn/entrypoints/worker.py")
READER = pathlib.Path("src/geekvpn/infrastructure/persistence/repositories/subscription_reader.py")
SCOPE = pathlib.Path("src/geekvpn/infrastructure/di/sync_scope.py")


def _function(path: pathlib.Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone")


def test_the_sweeps_run_once_per_shop():
    source = ast.unparse(_function(WORKER, "_tick_sync"))

    assert "self._shops()" in source
    assert "_tick_shop" in source


def test_each_shop_gets_its_own_scope():
    """Which is what picks up that shop's bot token."""
    source = ast.unparse(_function(WORKER, "_tick_shop"))

    assert "reseller_id=reseller_id" in source


def test_only_shops_that_can_actually_send_are_swept():
    """A reseller with no bot has no way to reach their customers, so sweeping
    them would queue messages nothing can deliver."""
    source = ast.unparse(_function(WORKER, "_shops"))

    assert "bot_token_encrypted" in source


def test_the_platform_is_swept_too():
    """`None` is a shop - ours - not an absence."""
    source = ast.unparse(_function(WORKER, "_shops"))

    assert "None" in source


def test_one_broken_shop_does_not_strand_the_others():
    source = ast.unparse(_function(WORKER, "_tick_sync"))

    assert "except Exception" in source
    assert "continue" in source


def test_broadcasts_are_not_dispatched_once_per_shop():
    """They already do their own per-shop loop. Registering the dispatcher on
    every pass would send each announcement once per reseller."""
    source = ast.unparse(_function(WORKER, "_tick_shop"))

    assert "if reseller_id is None" in source


def test_every_reminder_query_is_scoped():
    """All three, not the two somebody remembers to update."""
    for name in ("expiring_within", "with_traffic_usage", "idle_since"):
        assert "self._shop()" in ast.unparse(_function(READER, name)), name


def test_the_scope_passes_its_own_shop_to_the_reader():
    """Without this the reader defaults to the platform and the per-shop loop
    above sweeps our customers over and over."""
    source = ast.unparse(_function(SCOPE, "subscription_reader"))

    assert "reseller_id=self.reseller_id" in source
