"""Anything in the catalogue can be renamed from the panel.

`PATCH` has existed on categories, products and plans since the catalogue was
written, and the panel had a client method for none of them - so a name typed
once could never be corrected. The only way to fix a typo was to create a
second row and archive the first, which is how a catalogue ends up with two of
everything.

Same shape as the removal contract beside this: a route with no button is a
feature nobody has.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

CLIENT = pathlib.Path("admin/src/lib/api.ts")
SCREEN = pathlib.Path("admin/src/app/products/page.tsx")
DIALOG = pathlib.Path("admin/src/components/feature/rename-dialog.tsx")
ROUTER = pathlib.Path("src/geekvpn/presentation/api/routers/admin_catalog.py")

EDITABLE = [
    ("updateCategory", "/categories/{category_id}"),
    ("updateProduct", "/products/{product_id}"),
    ("updatePlan", "/plans/{plan_id}"),
]


@pytest.mark.parametrize(("method", "route"), EDITABLE)
def test_the_client_can_reach_the_update_route(method: str, route: str):
    client = CLIENT.read_text(encoding="utf-8")

    assert f"{method}:" in client
    assert "'PATCH'" in client


@pytest.mark.parametrize(("method", "route"), EDITABLE)
def test_the_route_exists_to_be_reached(method: str, route: str):
    source = ROUTER.read_text(encoding="utf-8")

    assert f'@router.patch(\n    "{route}"' in source


@pytest.mark.parametrize(("method", "route"), EDITABLE)
def test_the_screen_actually_calls_it(method: str, route: str):
    """The whole point: the routes were never the missing part."""
    assert f"api.{method}(" in SCREEN.read_text(encoding="utf-8")


def test_one_dialog_serves_all_three():
    """The field is the same field. Three near-identical dialogs is three
    places for the save handler to drift."""
    assert DIALOG.exists()
    assert SCREEN.read_text(encoding="utf-8").count("<RenameDialog") == 1


def test_the_dialog_refuses_an_empty_name():
    """A blank name on a product is a storefront row with nothing to click."""
    source = DIALOG.read_text(encoding="utf-8")

    assert "cleaned.length === 0" in source


def test_the_dialog_follows_the_row_it_was_opened_from():
    """One piece of state serves every row, so the field has to be reset when
    a different row opens it - otherwise it renames the right thing with the
    previous row's text."""
    source = DIALOG.read_text(encoding="utf-8")

    assert "useEffect" in source
    assert "setName(currentName)" in source


def test_a_server_that_refuses_deletion_says_how_many_are_on_it():
    """"It still has subscriptions" leaves an operator with no idea whether
    that is one test account or four hundred customers."""
    source = pathlib.Path(
        "src/geekvpn/presentation/api/routers/admin_panels.py"
    ).read_text(encoding="utf-8")

    assert "{live}" in source
