"""Webhook registration must not be able to take the bot process down.

The installer starts the bot before certbot has issued a certificate, so on
every fresh install Telegram is asked to reach a URL that is either not in DNS
yet or is served with the entrypoint's self-signed placeholder. It refuses, and
an unguarded `await bot.set_webhook(...)` in the lifespan turned that refusal
into a container restart loop - over a condition that resolves itself minutes
later, with no bot left running to receive the webhook once it did.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.app import register_webhook

pytestmark = pytest.mark.unit


class RejectingBot:
    """Telegram saying no, for any of the reasons it says no."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def set_webhook(self, url: str, **kwargs: object) -> bool:
        self.calls += 1
        raise self._error


class AcceptingBot:
    def __init__(self) -> None:
        self.url: str | None = None
        self.secret: str | None = None
        self.allowed: list[str] | None = None

    async def set_webhook(
        self,
        url: str,
        *,
        secret_token: str,
        drop_pending_updates: bool,
        allowed_updates: list[str],
    ) -> bool:
        self.url = url
        self.secret = secret_token
        self.allowed = allowed_updates
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Bad Request: bad webhook: SSL error"),
        ConnectionError("Cannot connect to host api.telegram.org"),
        TimeoutError(),
    ],
)
async def test_a_refused_registration_does_not_raise(settings, error: Exception) -> None:
    bot = RejectingBot(error)

    registered = await register_webhook(bot, settings, allowed_updates=["message"])

    assert registered is False
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_a_successful_registration_passes_the_configured_values(settings) -> None:
    bot = AcceptingBot()

    registered = await register_webhook(bot, settings, allowed_updates=["message"])

    assert registered is True
    assert bot.url == settings.telegram.webhook_url
    assert bot.secret == settings.telegram.webhook_secret.get_secret_value()
    assert bot.allowed == ["message"]
