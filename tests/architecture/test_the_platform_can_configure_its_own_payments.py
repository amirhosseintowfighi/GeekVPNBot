"""Every way the platform takes money is configurable from its own screen.

`GatewayAccounts` was written to serve both the operator and a reseller - its
docstring says so - and was mounted only inside the reseller drawer. So an
operator could configure an online gateway for every shop except their own,
and the section simply was not there to find.

The same shape as the other bugs in this codebase: finished code that one
entry point reaches and another does not. Structural, because that is how it
fails - nothing errors, the screen is just missing.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.architecture

ROOT = pathlib.Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "admin" / "src" / "app" / "settings" / "page.tsx"
DRAWER = ROOT / "admin" / "src" / "components" / "feature" / "reseller-drawer.tsx"


def _settings() -> str:
    return SETTINGS.read_text(encoding="utf-8")


def test_the_platform_can_add_a_card():
    assert "<CardsSection" in _settings()


def test_the_platform_can_add_an_online_gateway():
    """The reported gap: an operator looking for "درگاه بانکی" on their own
    settings screen found nothing, because the section existed only in the
    drawer that configures somebody else's shop."""
    assert "<GatewayAccounts" in _settings()


def test_a_reseller_still_gets_the_same_section():
    """One component, two mounts. Two copies would be two places for the
    validation and the confirm to drift."""
    assert "<GatewayAccounts" in DRAWER.read_text(encoding="utf-8")
