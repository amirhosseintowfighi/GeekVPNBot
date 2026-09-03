"""Saving a setting returns a valid response.

`SettingResponse` gained two required fields - `label_fa` and `kind` - and only
the list endpoint was updated to supply them. `PUT /admin/settings/{key}` still
built the response by hand, so every save failed at response validation and
answered 500. Not just the signup bonus: no setting could be changed at all,
and the panel showed the generic "مشکلی پیش آمد".

The read path was tested and green the whole time, which is the point: the two
endpoints shared a model and not a constructor.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from geekvpn.application.platform.settings_service import SIGNUP_BONUS_TOMAN
from geekvpn.presentation.api.routers.settings import _view
from geekvpn.presentation.api.schemas_auth import SettingResponse

pytestmark = pytest.mark.integration

ROUTER = pathlib.Path("src/geekvpn/presentation/api/routers/settings.py")


class _Record:
    """The shape `SettingsStore.set` hands back."""

    def __init__(self, key: str, value: object) -> None:
        self.key = key
        self.value = value
        self.description = "whatever"
        self.is_secret = False
        self.updated_at = None

    @property
    def display_value(self) -> object:
        return self.value


def test_the_response_a_save_returns_is_valid():
    """This is what raised. Building it is the whole test."""
    response = _view(_Record(SIGNUP_BONUS_TOMAN.key, 50_000))

    assert isinstance(response, SettingResponse)
    assert response.value == 50_000


def test_it_carries_the_fields_the_panel_needs():
    response = _view(_Record(SIGNUP_BONUS_TOMAN.key, 50_000))

    assert response.kind == "toman"
    assert response.label_fa.strip()


def test_a_key_the_registry_no_longer_declares_still_renders():
    """A row left in the table by a removed setting must not 500 the endpoint
    that reads it - the same class of failure, one level down."""
    response = _view(_Record("gone.from.the.registry", "x"))

    assert response.kind == "text"
    assert response.label_fa == "gone.from.the.registry"


def test_both_endpoints_build_the_response_the_same_way():
    """The actual defect: one model, two constructors, and only one of them
    updated. There is one constructor now, and this keeps it that way."""
    source = ROUTER.read_text(encoding="utf-8")

    assert source.count("SettingResponse(") == 1, (
        "a second hand-built response is how this broke the first time"
    )


def test_the_update_endpoint_uses_it():
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    update = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_setting"
    )

    assert "_view(record)" in ast.unparse(update)
