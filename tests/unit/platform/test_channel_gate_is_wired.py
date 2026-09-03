"""The join gate is reachable, scoped, and escapable.

A gate is the one feature where "written but not wired" is invisible in the
wrong direction: nothing appears broken, customers simply are not gated. And a
gate wired badly is worse than none - a locked door with the handle on the
outside.

Structural, because all three failures are: a middleware nobody registers, a
repository that forgot the shop, and a recheck button the gate itself swallows.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

FACTORY = pathlib.Path("src/geekvpn/presentation/bot/factory.py")
GATE = pathlib.Path("src/geekvpn/presentation/bot/channel_gate.py")
START = pathlib.Path("src/geekvpn/presentation/bot/handlers/start.py")
REPO = pathlib.Path("src/geekvpn/infrastructure/persistence/repositories/channels.py")
SCOPE = pathlib.Path("src/geekvpn/infrastructure/di/scope.py")
CLIENT = pathlib.Path("admin/src/lib/api.ts")
COMPONENT = pathlib.Path("admin/src/components/feature/required-channels.tsx")
SETTINGS_PAGE = pathlib.Path("admin/src/app/settings/page.tsx")
PORTAL_PAGE = pathlib.Path("admin/src/app/portal/page.tsx")


def _function(path: pathlib.Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from {path}")


def test_the_middleware_is_registered():
    """Otherwise nothing is gated and nothing looks wrong."""
    assert "ChannelGateMiddleware()" in FACTORY.read_text(encoding="utf-8")


def test_the_recheck_button_is_never_gated():
    """It is the only button that can release somebody. Gating it would be a
    door locked from the inside."""
    source = ast.unparse(_function(GATE, "__call__"))

    assert "_is_recheck" in source


def test_the_recheck_button_has_a_handler():
    """A callback nothing decodes answers "this is from an older version" - to
    a customer who has done exactly what they were told."""
    assert "on_gate_recheck" in START.read_text(encoding="utf-8")


def test_the_recheck_ignores_the_cache():
    """Somebody pressing it has just joined. Answering from a cached "no" tells
    them they have not done the thing they just did."""
    source = ast.unparse(_function(START, "on_gate_recheck"))

    assert "cache=None" in source


def test_only_a_pass_is_cached():
    """Caching a refusal leaves somebody staring at a gate they have already
    satisfied, for as long as the entry lives."""
    source = ast.unparse(_function(GATE, "unjoined"))

    assert "if not missing and cache is not None" in source


@pytest.mark.parametrize("method", ["active", "listing", "set_active", "remove"])
def test_every_query_carries_the_shop(method: str):
    """A reseller must not read, switch off or delete the platform's gate."""
    assert "_shop()" in ast.unparse(_function(REPO, method))


def test_the_scope_hands_the_repository_its_shop():
    """Without this the repository defaults to the platform and every
    reseller's bot gates on our channels."""
    source = ast.unparse(_function(SCOPE, "required_channels"))

    assert "self.reseller" in source


@pytest.mark.parametrize(
    "method",
    ["channels", "addChannel", "setChannelActive", "removeChannel",
     "myChannels", "addMyChannel", "setMyChannelActive", "removeMyChannel"],
)
def test_the_panel_can_reach_every_operation(method: str):
    assert f"{method}:" in CLIENT.read_text(encoding="utf-8")


def test_no_client_call_names_a_shop():
    """The API takes the shop from the token. A shop id in a URL would be one
    missing check away from a reseller editing our gate."""
    source = CLIENT.read_text(encoding="utf-8")
    channel_lines = [li for li in source.splitlines() if "/channels" in li]

    assert channel_lines
    assert not [li for li in channel_lines if "resellerId" in li]


def test_both_panels_show_it():
    assert "RequiredChannels" in SETTINGS_PAGE.read_text(encoding="utf-8")
    assert "RequiredChannels" in PORTAL_PAGE.read_text(encoding="utf-8")


def test_one_component_serves_both():
    """The platform's list and a reseller's are the same screen; two copies
    would be two places for the confirm and the validation to drift."""
    assert COMPONENT.exists()
    assert 'scope: \'platform\' | \'mine\'' in COMPONENT.read_text(encoding="utf-8")


def test_removing_a_channel_asks_first():
    assert "window.confirm" in COMPONENT.read_text(encoding="utf-8")


def test_the_operator_is_told_the_bot_must_be_an_admin():
    """The single most common way this is misconfigured, and the customer must
    never be the one who discovers it."""
    assert "ادمین" in COMPONENT.read_text(encoding="utf-8")
