"""Each reseller's own Telegram bot, and how one process serves many of them.

A reseller runs their own bot under their own @username. Their customers never
see this platform, which is the point: the reseller is selling their own
service and we are the supplier behind it.

Serving several bots from one process is only possible because the platform is
webhook-driven rather than polling. Polling needs one long-lived connection per
token; a webhook needs one route per token, and a route is free.

Three things here, each small:

* **the path** a tenant's updates arrive on, which carries the reseller id;
* **the secret** Telegram signs them with, derived per reseller so one leaked
  value does not authenticate another tenant's traffic;
* **the token check**, which asks Telegram who the token belongs to. That call
  is the only way to learn the bot's @username, and it is also the only honest
  way to tell a working token from a typo before somebody's customers are
  pointed at it.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Protocol

#: Telegram allows 1-256 characters of `A-Za-z0-9_-` in a webhook secret.
#: Hex is a safe subset and 32 characters is far more than the guessing
#: resistance this needs, given the secret is only the second line of defence
#: behind an unguessable path.
_SECRET_LENGTH = 32


def tenant_path(base_path: str, reseller_id: uuid.UUID) -> str:
    """Where one reseller's updates arrive.

    Under the platform's own webhook path rather than beside it, so an edge
    configuration that forwards the bot's path forwards every tenant with it -
    the alternative is a reseller whose bot silently receives nothing because
    nginx was never told about a second location.
    """
    return f"{base_path.rstrip('/')}/r/{reseller_id.hex}"


def tenant_secret(platform_secret: str, reseller_id: uuid.UUID) -> str:
    """The secret Telegram signs one tenant's updates with.

    Derived rather than stored: there is nothing to keep in sync, nothing to
    lose, and no second secrets table. Derived rather than *shared*, because a
    single value across every tenant means a leak from one reseller's edge
    authenticates traffic claiming to be any of them.
    """
    digest = hmac.new(
        platform_secret.encode("utf-8"),
        f"reseller:{reseller_id.hex}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return digest[:_SECRET_LENGTH]


@dataclass(frozen=True, slots=True)
class BotIdentity:
    """Who a token belongs to, as Telegram answers it."""

    bot_id: int
    username: str


class TokenChecker(Protocol):
    """Asks Telegram to identify a bot token.

    A port because it is a network call: the service that stores a token must
    be testable without one, and the check is exactly the part worth faking.
    """

    async def identify(self, token: str) -> BotIdentity: ...


class InvalidBotToken(Exception):
    """The token is malformed, revoked, or belongs to nothing.

    Raised before storing. A token that has never been checked is a bot that
    will silently receive nothing, discovered by a reseller whose customers
    are already waiting.
    """


__all__ = [
    "BotIdentity",
    "InvalidBotToken",
    "TokenChecker",
    "tenant_path",
    "tenant_secret",
]
