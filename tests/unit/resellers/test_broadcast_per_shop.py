"""A scheduled broadcast is sent by the shop that wrote it.

Two things had to be true and neither was. Scheduled broadcasts never fired at
all - the worker's own comment said `BroadcastService` needed a reader with no
SQL implementation, `SqlAudienceResolver` had since been written, and nobody
came back to remove the note. And a broadcast had no shop, so a reseller's
announcement would have resolved over every customer on the platform and gone
out from our bot.

These read the source, because the failure is structural: a dispatcher that
builds one scope for every broadcast is wrong in a way no assertion about a
single send would catch.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

WORKER = pathlib.Path("src/geekvpn/entrypoints/worker.py")
REPOSITORY = pathlib.Path(
    "src/geekvpn/infrastructure/persistence/repositories/sync_notifications.py"
)


def _function(path: pathlib.Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone")


def _method(class_name: str, name: str) -> ast.AST:
    tree = ast.parse(REPOSITORY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return child
    raise AssertionError(f"{class_name}.{name} is gone")


def test_scheduled_broadcasts_are_dispatched_at_all():
    """They never were. The job existed, the service existed, the resolver
    existed - and nothing registered the handler.

    Registration lives in `_tick_shop` now that the sweeps run once per shop.
    Still the same guarantee: something registers the dispatcher.
    """
    source = ast.unparse(_function(WORKER, "_tick_shop"))

    assert "JobKind.BROADCAST_DISPATCH" in source


def test_each_broadcast_is_sent_under_its_own_shop():
    """The structural half.

    One scope for every due broadcast would send each shop's message from our
    bot, to an audience drawn from everybody - and it would look like working
    code, because it would send.
    """
    source = ast.unparse(_function(WORKER, "_dispatch_broadcasts"))

    assert "reseller_id=reseller_id" in source
    # A scope built inside the loop, not once outside it.
    assert source.count("build_sync_scope") >= 2


def test_one_shop_failing_does_not_strand_the_others():
    source = ast.unparse(_function(WORKER, "_dispatch_broadcasts"))

    assert "except Exception" in source
    assert "rollback" in source


def test_due_is_deliberately_not_scoped():
    """The one query here that must see every shop.

    The worker collects all due broadcasts in one pass and sends each under its
    own shop. A filter on `due` would leave every reseller's scheduled
    announcement waiting forever, which is a silence nobody would notice.
    """
    source = ast.unparse(_method("SyncBroadcastRepository", "due"))

    assert "_shop()" not in source


def test_what_a_person_looks_at_is_scoped():
    """The listing is a screen. A reseller must not read the platform's
    announcements, or the platform a reseller's."""
    assert "_shop()" in ast.unparse(_method("SyncBroadcastRepository", "listing"))


def test_a_new_broadcast_is_stamped_with_its_shop():
    """Without it every broadcast is the platform's, and the scoping above
    filters on a column nobody sets."""
    source = ast.unparse(_method("SyncBroadcastRepository", "save"))

    assert "reseller_id = self._reseller_id" in source


def test_the_worker_takes_a_few_at_a_time():
    """Each one sends to its whole audience before the next begins, so a tick
    that picks up fifty is a tick that runs for an hour."""
    source = ast.unparse(_function(WORKER, "_dispatch_broadcasts"))

    assert "_BROADCAST_BATCH" in source
