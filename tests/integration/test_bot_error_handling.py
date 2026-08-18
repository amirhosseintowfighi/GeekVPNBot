"""A failing handler must not become a redelivery loop.

Telegram retries any update the webhook does not answer 2xx, forever and
without meaningful backoff. So an exception escaping the webhook is not one
failure: it is the same failure repeating against every worker for as long as
the bug exists.

The webhook already carried a comment promising it always acks. Nothing made
that true - `feed_update` re-raised straight through it.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.app import SECRET_HEADER
from geekvpn.presentation.bot.factory import ROUTERS
from geekvpn.presentation.bot.handlers import errors
from tests.conftest import BOT_WEBHOOK_SECRET

pytestmark = pytest.mark.integration

UPDATE = {
    "update_id": 1,
    "message": {"message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"}},
}


class ExplodingDispatcher:
    """Stands in for a dispatcher whose handler raised."""

    def __init__(self) -> None:
        self.calls = 0

    async def feed_update(self, **_kw: object) -> None:
        self.calls += 1
        raise RuntimeError("a handler blew up")


def test_the_errors_router_is_registered_before_everything_else() -> None:
    """Registered at all is the point; first is where it is easiest to see."""
    assert errors in ROUTERS
    assert ROUTERS[0] is errors


def test_the_error_handler_reports_the_update_as_handled() -> None:
    """Returning False re-raises into the webhook, which is the 500 we are
    avoiding. The signature has to keep saying True."""
    import inspect

    source = inspect.getsource(errors.on_error)
    assert "return True" in source
    assert "return False" not in source


def test_a_handler_that_raises_still_acks(webhook) -> None:
    """The property that stops the loop: 200 and {"ok": true}, whatever
    happened underneath."""
    client, dispatcher, secret = webhook
    dispatcher.calls = 0

    response = client.post("/telegram/webhook", json=UPDATE, headers={SECRET_HEADER: secret})

    assert dispatcher.calls == 1, "the update never reached the dispatcher"
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_every_retry_is_acked_too(webhook) -> None:
    """One ack is not enough: Telegram redelivers, and each redelivery must
    also terminate rather than feed the loop."""
    client, dispatcher, secret = webhook
    dispatcher.calls = 0

    codes = {
        client.post("/telegram/webhook", json=UPDATE, headers={SECRET_HEADER: secret}).status_code
        for _ in range(3)
    }

    assert codes == {200}
    assert dispatcher.calls == 3


def test_a_bad_secret_is_still_rejected(webhook) -> None:
    """Acking everything must not become accepting everything: an unsigned
    update is refused before it reaches the dispatcher."""
    client, dispatcher, _secret = webhook
    dispatcher.calls = 0

    response = client.post("/telegram/webhook", json=UPDATE, headers={SECRET_HEADER: "wrong"})

    assert response.status_code == 403
    assert dispatcher.calls == 0


@pytest.fixture
def webhook(bot_client):
    """The shared bot client, with a dispatcher that fails on demand.

    The real dispatcher is restored afterwards so the other webhook tests are
    not left talking to a stub.
    """
    app = bot_client.app
    original = app.state.dispatcher
    dispatcher = ExplodingDispatcher()
    app.state.dispatcher = dispatcher
    try:
        yield bot_client, dispatcher, BOT_WEBHOOK_SECRET
    finally:
        app.state.dispatcher = original
