"""Every declared setting is visible and editable in the panel.

The settings screen filtered rows against a hand-written list of five
`pricing.*` prefixes. Not one of the eight registered keys starts with
`pricing.`, so the filter matched nothing and the page rendered no cards at
all - an operator could not change a single setting, and the screen looked
merely empty rather than broken.

It also read `labelFa` and `kind` off a response that carried neither, so every
row would have had a blank label and a numeric input. That second part matters
on its own: a numeric input on a text setting reduces it to zero the moment
somebody types in it.

Adding a setting must never again mean adding it to a second list somewhere
else in order for anybody to see it.
"""

from __future__ import annotations

import pathlib

import pytest

from geekvpn.application.platform.settings_service import SETTING_REGISTRY

pytestmark = pytest.mark.unit

SCREEN = pathlib.Path("admin/src/app/settings/page.tsx")
ROUTER = pathlib.Path("src/geekvpn/presentation/api/routers/settings.py")
SCHEMA = pathlib.Path("src/geekvpn/presentation/api/schemas_auth.py")


def test_every_setting_has_a_label_an_operator_can_read():
    """`description` is English and for us. The panel is Persian."""
    unlabelled = [key for key, d in SETTING_REGISTRY.items() if not d.label_fa.strip()]

    assert not unlabelled, f"no Persian label: {unlabelled}"


def test_every_setting_declares_how_to_render_it():
    known = {"boolean", "text", "number", "toman", "bps", "count"}
    wrong = {key: d.kind for key, d in SETTING_REGISTRY.items() if d.kind not in known}

    assert not wrong, wrong


def test_a_text_setting_is_not_rendered_as_a_number():
    """The one that silently destroys data: a numeric input on a message field
    turns it into ۰ on the first keystroke."""
    assert SETTING_REGISTRY["wallet.signup_bonus_note_fa"].kind == "text"
    assert SETTING_REGISTRY["platform.maintenance_message"].kind == "text"
    assert SETTING_REGISTRY["support.telegram_handle"].kind == "text"


def test_an_amount_is_rendered_as_money():
    assert SETTING_REGISTRY["wallet.signup_bonus_toman"].kind == "toman"


def test_the_api_sends_what_the_screen_reads():
    """Both were invented client-side from fields that were never sent."""
    schema = SCHEMA.read_text(encoding="utf-8")

    assert "label_fa: str" in schema
    assert "kind: str" in schema
    assert "label_fa=" in ROUTER.read_text(encoding="utf-8")


def test_the_screen_groups_by_namespace_rather_than_a_fixed_list():
    """The bug itself: a hardcoded prefix list silently drops anything new."""
    source = SCREEN.read_text(encoding="utf-8")

    # The grouping is computed from the key, not looked up in a list. Naming
    # the helper is not enough - the call site is what decides what is drawn.
    assert "groupTitle(namespaceOf(setting.key))" in source
    assert "function namespaceOf(" in source
    assert "prefix: 'pricing.rounding'" not in source
    # And nothing filters rows out before they reach a card.
    assert "startsWith(group.prefix)" not in source


def test_a_namespace_nobody_named_still_gets_a_card():
    """A new setting must appear the moment the backend declares it, even
    before anybody writes a Persian title for its group."""
    source = SCREEN.read_text(encoding="utf-8")

    assert "OTHER_TITLE" in source


@pytest.mark.parametrize("key", sorted(SETTING_REGISTRY))
def test_no_setting_lands_in_an_unnamed_group(key: str):
    """Not a correctness requirement - the catch-all covers it - but a group
    called "سایر" is a label nobody wrote, and every shipped setting deserves
    better than that."""
    named = SCREEN.read_text(encoding="utf-8")
    namespace = key.split(".")[0]

    assert f"  {namespace}: '" in named, f"{namespace} has no Persian group title"
