"""Every notification's call to action is a button, and every button works.

Two failures met here.

The sender dropped `action` entirely, on the grounds that a broken button is
worse than none. So every expiry warning, quota warning and wallet notice
arrived as text telling somebody to go and do something, with no way to do it.

And the typed helpers in the bot process that *did* build buttons -
`expiring_soon`, `quota_warning`, `expired` - were called by nothing at all.
Real delivery never went near them, which is why nobody noticed the first
failure. This reads the source, because "nothing calls it" is invisible to any
test that calls it.
"""

from __future__ import annotations

import pathlib

import pytest

from geekvpn.domain.notifications.message import CATALOG
from geekvpn.infrastructure.notifications.telegram import ACTION_BUTTONS, _action_button

pytestmark = pytest.mark.unit

HANDLERS = pathlib.Path("src/geekvpn/presentation/bot/handlers")


def _handled_nav_targets() -> set[str]:
    """Every `to` value the bot has a handler for, read from the source."""
    targets: set[str] = set()
    for path in HANDLERS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "NavCB.filter(F.to ==" in line:
                targets.add(line.split('"')[1])
    return targets


def test_every_action_button_leads_somewhere_the_bot_handles():
    """A button whose callback nothing decodes answers "this is from an older
    version" - which is the failure the sender was avoiding by sending no
    button at all. This is what makes sending one safe."""
    handled = _handled_nav_targets()
    assert handled, "found no nav handlers at all; the reader is broken"

    for action, (_label, data) in ACTION_BUTTONS.items():
        prefix, _, target = data.partition(":")
        assert prefix == "nav", f"{action} does not build a NavCB"
        assert target in handled, f"{action} sends the customer to an unhandled screen"


def test_every_template_action_has_a_button():
    """A template whose action is not in the table sends no button, silently.
    That is the right behaviour and the wrong thing to ship."""
    used = {t.action for t in CATALOG.values() if t.action}

    missing = used - set(ACTION_BUTTONS)

    assert not missing, f"templates point at actions with no button: {sorted(missing)}"


def test_a_template_with_no_action_sends_no_button():
    assert _action_button(None) is None
    assert _action_button("") is None


def test_an_unknown_action_sends_no_button_rather_than_a_guess():
    assert _action_button("somewhere_new") is None


def test_the_button_carries_a_label_and_a_callback():
    button = _action_button("support")

    assert button is not None
    assert button["callback_data"] == "nav:support"
    assert button["text"].strip()
