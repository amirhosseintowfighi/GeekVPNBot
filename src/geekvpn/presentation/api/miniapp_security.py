"""Authenticating a Mini App request.

The Mini App sends ``Authorization: tma <initData>`` on every call rather than
exchanging the initData for a JWT once. That is the shape Telegram's own SDK
encourages, and it is the better fit here: initData is already signed and
short-lived, so a token exchange would add a second credential to keep, refresh
and revoke without removing the first.

The signature is re-verified on **every** request. It is an HMAC over a handful
of fields, so the cost is negligible next to the database work that follows, and
the alternative - trusting a first verification for the rest of a session -
means a replayed header outlives the window Telegram set on it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from geekvpn.application.bot.services import BotServices
from geekvpn.application.identity.dto import RequestContext
from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.bot.services import build_bot_services
from geekvpn.presentation.api.errors import AuthenticationError
from geekvpn.presentation.api.security import ScopeDep

#: The scheme Telegram's Mini App SDK uses. Compared case-insensitively because
#: the SDK's own examples disagree with each other about the capitalisation.
SCHEME = "tma"


def _init_data(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("An Authorization: tma <initData> header is required.")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != SCHEME or not value.strip():
        raise AuthenticationError("An Authorization: tma <initData> header is required.")
    return value.strip()


async def current_mini_app_user(
    scope: ScopeDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Verify the initData signature and resolve it to a customer.

    A bad signature and an unknown scheme produce the same 401 with the same
    message: telling an attacker which half of the header was wrong is free
    information.
    """
    result = await scope.authenticate_telegram.from_mini_app(
        _init_data(authorization),
        context=RequestContext(device_label="telegram-mini-app"),
    )
    return result.user


CurrentMiniAppUser = Annotated[User, Depends(current_mini_app_user)]


async def mini_app_services(scope: ScopeDep) -> BotServices:
    """The same bundle the bot handlers get.

    The Mini App and the bot are two front-ends over one set of use cases, so
    they share the read models rather than growing a parallel set that can
    disagree about what a subscription looks like.

    ``fetch_receipt`` is absent on purpose: a Mini App upload arrives as bytes
    over HTTP, not as a Telegram file id, so the receipt route below digests
    what it was given instead of downloading anything.
    """
    return build_bot_services(scope)


ServicesDep = Annotated[BotServices, Depends(mini_app_services)]


__all__ = ["SCHEME", "CurrentMiniAppUser", "ServicesDep", "current_mini_app_user"]
