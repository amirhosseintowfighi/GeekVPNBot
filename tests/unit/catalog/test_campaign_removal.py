"""Removing a campaign from the panel.

Archiving already existed on the aggregate, in the service and behind a state
endpoint - and nothing in the admin panel called it. The campaigns screen had an
activate/pause switch and no way to get rid of a row at all, which is the same
"written, tested, unreachable" shape this project keeps hitting.

Archived, not deleted, for the reason coupons are: a campaign that has ever
discounted an order is named by that order, and removing the row turns a
historical invoice into an unexplainable price. So "delete" has to mean "leaves
the list" - and if archived rows kept appearing, the button would look broken.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

ROUTER = pathlib.Path("src/geekvpn/presentation/api/routers/admin_catalog.py")
SERVICE = pathlib.Path("src/geekvpn/application/catalog/promotion_admin.py")
REPO = pathlib.Path("src/geekvpn/infrastructure/persistence/repositories/catalog.py")
SCREEN = pathlib.Path("admin/src/app/campaigns/page.tsx")
CLIENT = pathlib.Path("admin/src/lib/api.ts")


def _function(path: pathlib.Path, name: str, *, inside: str | None = None) -> ast.AST:
    """Find one function, optionally the one inside a named class.

    `inside` is not optional decoration: four repositories in catalog.py have a
    `list_all`, and a reader that takes the first match asserts happily about
    the wrong one - which is a green test for code nobody changed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes: list[ast.AST] = [tree]
    if inside is not None:
        scopes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == inside
        ]
        assert scopes, f"{inside} is gone from {path}"
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
                return node
    raise AssertionError(f"{name} is gone from {path}")


def test_there_is_an_endpoint_to_remove_a_campaign():
    source = ROUTER.read_text(encoding="utf-8")

    assert '@router.delete(\n    "/campaigns/{campaign_id}"' in source


def test_removing_archives_rather_than_deletes():
    """A hard delete would orphan the discount on every order that used it."""
    source = ast.unparse(_function(ROUTER, "archive_campaign"))

    assert "'archive'" in source or '"archive"' in source


def test_an_archived_campaign_leaves_the_list():
    """Otherwise the operator presses delete and the row stays put."""
    source = ast.unparse(
        _function(REPO, "list_all", inside="SqlAlchemyCampaignRepository")
    )

    assert "include_archived" in source
    assert "archived" in source


def test_the_operator_can_still_ask_for_them():
    """Gone from the screen is not gone from the record: an archived campaign
    is still the explanation for a discount on somebody's old invoice."""
    assert "include_archived" in ast.unparse(_function(SERVICE, "list_campaigns"))


def test_the_panel_actually_calls_it():
    """The whole point. The endpoint existed for archiving via the state route
    long before this, and no screen ever used it."""
    assert "archiveCampaign" in CLIENT.read_text(encoding="utf-8")
    assert "archiveCampaign" in SCREEN.read_text(encoding="utf-8")


def test_the_button_asks_first():
    """It is the row leaving the screen with no undo beside it."""
    assert "window.confirm" in SCREEN.read_text(encoding="utf-8")


def test_the_button_is_hidden_from_somebody_who_cannot_use_it():
    source = SCREEN.read_text(encoding="utf-8")

    assert "can('campaigns.write')" in source
