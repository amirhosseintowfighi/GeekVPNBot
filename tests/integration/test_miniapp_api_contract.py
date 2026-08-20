"""The Mini App and the backend must agree on the URLs.

The Mini App shipped calling sixteen endpoints that did not exist at all. This
is the same guard as `test_admin_api_contract.py`, pointed at `miniapp/src`: it
extracts what the client calls and diffs it against the registered routes, so
the gap can only shrink.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from geekvpn.presentation.api.app import create_app

pytestmark = pytest.mark.integration

MINIAPP_SRC = Path(__file__).resolve().parents[2] / "miniapp" / "src"

#: Mini App calls with no backend yet. Each is a missing reader, not a naming
#: difference; the routes exist and answer 501 so the client gets a clear
#: signal instead of a 404 it cannot distinguish from a typo.
KNOWN_GAPS: frozenset[str] = frozenset()

_TEMPLATE = re.compile(r"\$\{[^}]*\}")


def called_paths() -> set[str]:
    found: set[str] = set()
    for file in list(MINIAPP_SRC.rglob("*.ts")) + list(MINIAPP_SRC.rglob("*.tsx")):
        text = file.read_text(encoding="utf-8")
        for raw in re.findall(r"[`'\"](/api/miniapp/[^`'\"]*)[`'\"]", text):
            path = raw.split("?")[0]
            found.add(_TEMPLATE.sub("{id}", path).rstrip("/"))
    return found


def registered_paths() -> set[str]:
    return {
        re.sub(r"\{[^}]*\}", "{id}", path)
        for path in create_app().openapi()["paths"]
        if path.startswith("/api/miniapp/")
    }


def test_the_miniapp_client_is_actually_being_read() -> None:
    assert MINIAPP_SRC.is_dir()
    assert called_paths()


def test_every_endpoint_the_miniapp_calls_is_registered() -> None:
    missing = called_paths() - registered_paths() - KNOWN_GAPS
    assert not missing, (
        "The Mini App calls endpoints the backend does not serve:\n  "
        + "\n  ".join(sorted(missing))
        + "\nEither register the route or add it to KNOWN_GAPS with a reason."
    )


def test_no_known_gap_has_been_quietly_closed() -> None:
    closed = KNOWN_GAPS & registered_paths()
    assert not closed, (
        "These are now registered and must be removed from KNOWN_GAPS:\n  "
        + "\n  ".join(sorted(closed))
    )


def test_the_root_layout_loads_the_telegram_sdk() -> None:
    """Telegram does not inject its SDK into a Mini App - the page must load it.

    Without the script `window.Telegram` never exists, so `getInitData()`
    returns an empty string, every request goes out with no Authorization
    header and the entire Mini App answers 401 inside a real Telegram client.
    """
    layout = (MINIAPP_SRC / "app" / "layout.tsx").read_text(encoding="utf-8")

    assert "telegram.org/js/telegram-web-app.js" in layout
    assert "beforeInteractive" in layout, (
        "the SDK must exist before hydration; initTelegram() runs in an effect"
    )
