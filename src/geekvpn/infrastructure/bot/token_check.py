"""Asking Telegram who a bot token belongs to.

`getMe` over plain HTTP rather than through aiogram: the API process stores the
token and has no bot framework, and constructing a `Bot` to make one call would
open a session that then has to be closed on every error path.

Two things come back that matter. The username, which is the only way to show
an operator which bot a reseller has configured without decrypting anything -
and the fact that the call succeeded at all, which is the difference between a
working token and a typo nobody notices until customers are waiting.
"""

from __future__ import annotations

import httpx

from geekvpn.application.resellers.tenant_bots import BotIdentity, InvalidBotToken
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

#: Short. An operator is watching a spinner, and a Telegram that is slow to
#: answer `getMe` is a Telegram that will be slow to deliver updates too.
TIMEOUT_SECONDS = 8.0


class HttpTokenChecker:
    async def identify(self, token: str) -> BotIdentity:
        token = token.strip()
        # Checked here rather than only by Telegram: a value with a newline or
        # a space in it produces a URL that fails in a way whose error message
        # says nothing about the token.
        if not token or ":" not in token or any(c.isspace() for c in token):
            raise InvalidBotToken("That does not look like a bot token.")

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        except httpx.HTTPError as failure:
            # Not "the token is bad" - we do not know that. Telegram was
            # unreachable, and saying otherwise would have an operator
            # regenerating a perfectly good token.
            logger.info("reseller.token_check_unreachable")
            raise InvalidBotToken("Telegram could not be reached to verify the token.") from failure

        if response.status_code != httpx.codes.OK:
            raise InvalidBotToken("Telegram rejected that token.")

        try:
            result = response.json()["result"]
            return BotIdentity(bot_id=int(result["id"]), username=str(result["username"]))
        except (KeyError, ValueError, TypeError) as failure:
            raise InvalidBotToken("Telegram's answer was not a bot.") from failure

    async def register_webhook(self, *, token: str, url: str, secret: str) -> None:
        """Point one reseller's bot at its own path on this platform.

        `drop_pending_updates` on purpose: whatever queued while the bot was
        unconfigured is addressed to a bot that did not answer, and replaying it
        would greet a reseller's customers with a burst of stale menus.
        """
        await self._call(
            token,
            "setWebhook",
            {"url": url, "secret_token": secret, "drop_pending_updates": True},
        )

    async def clear_webhook(self, *, token: str) -> None:
        await self._call(token, "deleteWebhook", {"drop_pending_updates": True})

    async def _call(self, token: str, method: str, payload: dict[str, object]) -> None:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token.strip()}/{method}", json=payload
                )
        except httpx.HTTPError as failure:
            raise InvalidBotToken("Telegram could not be reached.") from failure

        if response.status_code != httpx.codes.OK:
            try:
                detail = str(response.json().get("description", ""))
            except ValueError:
                detail = response.text[:200]
            logger.info("reseller.webhook_call_refused", method=method, detail=detail)
            raise InvalidBotToken(detail or f"Telegram refused {method}.")


__all__ = ["HttpTokenChecker"]
