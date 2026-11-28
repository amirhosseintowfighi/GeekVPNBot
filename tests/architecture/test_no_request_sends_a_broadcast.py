"""No HTTP route sends a broadcast inside the request.

`BroadcastService.send_now` makes one Telegram call per recipient before it
returns. Behind nginx's 120s it answered the operator with a gateway error
while the send went on, and every retry composed a new broadcast to everybody.
Routes call `queue_now`; the worker's BROADCAST_DISPATCH sends.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROUTERS = Path(__file__).resolve().parents[2] / "src" / "geekvpn" / "presentation" / "api"


def test_no_api_module_calls_send_now() -> None:
    offenders = [
        str(path.relative_to(ROUTERS))
        for path in ROUTERS.rglob("*.py")
        if ".send_now(" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"send a broadcast inside a request: {offenders}"
