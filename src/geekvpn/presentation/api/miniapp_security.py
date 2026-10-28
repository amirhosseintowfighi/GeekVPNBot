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

Verification only. This used to run the full login use case, which minted a
session and a refresh token and wrote a login audit row on every single call;
token issuance now lives on ``/api/v1/auth/telegram/mini-app`` alone.

The Android app reaches the same routes with ``Authorization: Bearer <jwt>``,
an access token from its own sign-in (``/api/app/auth``). Both schemes resolve
to the same ``UserProfile``, so every Mini App endpoint serves the app without
a second copy. A Bearer token is held to the rules of ``/api/v1/auth/*``:
signature, expiry, revocation list, and a customer - not an admin - subject.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Header

from geekvpn.application.bot.services import BotServices
from geekvpn.application.identity.dto import UserProfile
from geekvpn.domain.base.errors import AuthenticationError, DomainError
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.errors import SessionRevokedError
from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.infrastructure.bot.services import build_bot_services
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.security.telegram import TelegramSignatureVerifier
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import ScopeDep

#: The scheme Telegram's Mini App SDK uses. Compared case-insensitively because
#: the SDK's own examples disagree with each other about the capitalisation.
logger = get_logger(__name__)

SCHEME = "tma"
#: The Android app's scheme: a customer access token.
BEARER = "bearer"

_REQUIRED = "An Authorization: tma <initData> or Bearer <token> header is required."

#: Which shop's bot opened the Mini App: a reseller id, from the `shop` query
#: parameter their bot's menu button carries. Absent in the platform's own bot.
SHOP_HEADER = "X-Shop"


def _credential(authorization: str | None) -> tuple[str, str]:
    """(scheme, value), the scheme lower-cased. Anything else is one 401."""
    if not authorization:
        raise AuthenticationError(_REQUIRED)
    scheme, _, value = authorization.partition(" ")
    scheme = scheme.lower()
    if scheme not in (SCHEME, BEARER) or not value.strip():
        raise AuthenticationError(_REQUIRED)
    return scheme, value.strip()


async def current_mini_app_user(
    scope: ScopeDep,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    shop: Annotated[str | None, Header(alias=SHOP_HEADER)] = None,
) -> UserProfile:
    """Verify the initData signature or the access token, and resolve it to a customer.

    A bad signature and an unknown scheme produce the same 401 with the same
    message: telling an attacker which half of the header was wrong is free
    information.
    """
    try:
        scheme, value = _credential(authorization)
        if scheme == BEARER:
            return await _bearer_user(value, scope=scope, container=container)
        if shop:
            return await _shop_user(value, shop, scope=scope, container=container)
        return await scope.authenticate_telegram.verify_mini_app_request(value)
    except DomainError as failure:
        # Which of them, in the log.
        #
        # Six different things produce this one 401 - no header, wrong scheme,
        # empty initData, a hash that does not match, data older than the
        # freshness window, no user object - and they need completely different
        # fixes. The response deliberately says none of it, because telling an
        # attacker which half of the header was wrong is free information. The
        # operator reading the log has already proven they own the server.
        #
        # The initData itself is never logged: it is a valid credential until
        # it expires, and a log file is not the place for one. Its length
        # separates "empty" from "present and rejected", which is the only part
        # that matters here.
        logger.info(
            "miniapp.auth_rejected",
            reason=str(failure),
            header_present=authorization is not None,
            init_data_length=len(authorization or "") - len(SCHEME) - 1,
        )
        raise


async def _shop_user(init_data: str, shop: str, *, scope: Any, container: Any) -> UserProfile:
    """A customer of a reseller's shop, from initData their bot signed.

    The header only names the shop; the signature is what proves it. It is
    checked with that shop's own bot token, so naming a shop without its bot's
    signature - or the platform's signature under a shop's name - is the same
    401 as any other bad initData. A shop that is closed, or has no bot, is too.

    The shop then goes on the scope, as the bot's identity middleware puts it
    there for an update: prices, payment methods and orders all read it, and a
    request that forgot it would be a reseller's customer shown our prices.
    """
    try:
        reseller_id = uuid.UUID(hex=shop)
    except ValueError as failure:
        raise AuthenticationError(_REQUIRED) from failure
    reseller = await scope.resellers.get(reseller_id)
    token = await scope.resellers.bot_token(reseller_id) if reseller else None
    if reseller is None or reseller.status is ResellerStatus.CLOSED or not token:
        raise AuthenticationError(_REQUIRED)
    verifier = TelegramSignatureVerifier(bot_token=token)
    user: UserProfile = await scope.authenticate_telegram.verify_mini_app_request(
        init_data, verifier=verifier, reseller_id=reseller_id.hex
    )
    scope.reseller = reseller
    scope.reseller_texts = await scope.resellers.texts(reseller_id)
    return user


async def _bearer_user(token: str, *, scope: ScopeDep, container: ContainerDep) -> UserProfile:
    """The same checks `get_current_user` makes, then the customer's profile.

    An admin token is refused here as it is on `/api/v1/auth/me`: the two
    populations have different lifetimes and threat models, and an admin
    session must not be able to act as a customer.
    """
    claims = container.access_tokens.decode(token)
    if await container.revocations.is_revoked(
        session_id=claims.session_id,
        subject_id=claims.subject_id,
        issued_at=claims.issued_at,
    ):
        raise SessionRevokedError()
    if claims.subject_type is not SubjectType.USER:
        raise AuthenticationError(_REQUIRED)
    return await scope.authenticate_telegram.profile_of(claims.subject_id)


CurrentMiniAppUser = Annotated[UserProfile, Depends(current_mini_app_user)]


async def mini_app_services(scope: ScopeDep, _user: CurrentMiniAppUser) -> BotServices:
    """The same bundle the bot handlers get.

    The Mini App and the bot are two front-ends over one set of use cases, so
    they share the read models rather than growing a parallel set that can
    disagree about what a subscription looks like.

    ``fetch_receipt`` is absent on purpose: a Mini App upload arrives as bytes
    over HTTP, not as a Telegram file id, so the receipt route below digests
    what it was given instead of downloading anything.

    Depends on the user, so the shop is on the scope before the bundle is
    built - FastAPI resolves it once per request, so this costs nothing.
    """
    return build_bot_services(scope)


ServicesDep = Annotated[BotServices, Depends(mini_app_services)]


__all__ = ["SCHEME", "SHOP_HEADER", "CurrentMiniAppUser", "ServicesDep", "current_mini_app_user"]
