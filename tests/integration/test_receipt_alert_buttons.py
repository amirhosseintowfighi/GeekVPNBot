"""The alert's buttons must be ones the bot can decode.

The receipt alert is assembled in the synchronous scope, which cannot import
the bot: `import-linter` forbids infrastructure from reaching into
presentation, and that is the right rule. The consequence is that the callback
data is written out by hand there and parsed by `AdminCB` here, in two layers
that never meet.

A mismatch is silent in the worst way. The message arrives, the image is there,
the operator taps approve - and the bot answers "this button is from an older
version", because nothing decoded it. So the two spellings are compared.
"""

from __future__ import annotations

import inspect
import re

import pytest

from geekvpn.application.notifications.operator_alerts import ReceiptAlerts
from geekvpn.presentation.bot.ui.callbacks import AdminCB

pytestmark = pytest.mark.integration


def _emitted() -> list[str]:
    """The callback strings the alert builds, with the id filled in."""
    source = inspect.getsource(ReceiptAlerts.on_proof_submitted)
    return [
        template.replace("{event.payment_id}", "abc123")
        for template in re.findall(r'f"(adm:[^"]*)"', source)
    ]


def test_the_alert_builds_buttons() -> None:
    assert len(_emitted()) == 2


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_the_bot_produces_the_same_string(action: str) -> None:
    expected = AdminCB(action=action, ref="abc123").pack()

    assert expected in _emitted(), (
        f"the alert's {action} button does not match what AdminCB packs "
        f"({expected!r}); tapping it would answer 'this button is from an "
        "older version'"
    )


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_the_bot_can_decode_what_the_alert_sends(action: str) -> None:
    """The other direction, through the real parser."""
    sent = next(data for data in _emitted() if f":{action}:" in data)
    decoded = AdminCB.unpack(sent)

    assert decoded.action == action
    assert decoded.ref == "abc123"
