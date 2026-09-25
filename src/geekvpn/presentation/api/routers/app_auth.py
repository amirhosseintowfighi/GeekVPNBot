"""Sign-in for the GeekVPN Android app.

The app cannot present a Telegram signature, so it is approved from inside the
bot instead (see `AppLinkLogin`): `start` returns a deep link and a poll
token, the customer taps "approve" in Telegram, and `poll` hands back a normal
customer session. From then on the app is an ordinary Bearer client: it
refreshes with `/api/v1/auth/refresh`, signs out with `/api/v1/auth/logout`,
and calls the Mini App's `/api/miniapp/*` routes with its access token.

Unversioned and outside `/api/miniapp`, like the Mini App's own prefix: this
is the contract of one client that ships on its own release cycle.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import ConfigDict, Field

from geekvpn.application.identity.app_link_login import START_PARAM_PREFIX
from geekvpn.application.identity.app_password_login import AppLoginDevice
from geekvpn.application.identity.dto import AuthenticationResult
from geekvpn.domain.identity.app_login import AppLoginStatus
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import ContextDep, ScopeDep

router = APIRouter(prefix="/api/app/auth", tags=["app-auth"])

#: How long one poll may wait for the customer to decide. Under the usual
#: 30-60s proxy read timeouts, with room to spare.
POLL_WAIT_SECONDS = 25.0
#: How often a waiting poll looks again. Each look is one indexed SELECT in a
#: transaction of its own, so nothing is held open between looks.
POLL_INTERVAL_SECONDS = 1.0


class AppLinkStartRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64)
    device_name: str = Field(default="", max_length=64)
    platform: str = Field(default="android", max_length=16)
    app_version: str = Field(default="", max_length=32)


class AppLinkStartResponse(ApiModel):
    request_id: uuid.UUID
    poll_token: str
    #: `https://t.me/<bot>?start=applogin_<code>`. Open it with Telegram; a
    #: browser falls through to Telegram's own "open in app" page.
    deep_link: str
    expires_in: int


class AppLinkPollRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    poll_token: str = Field(min_length=16, max_length=128)
    #: False answers at once; true (the default) waits up to 25 seconds for a
    #: decision.
    wait: bool = True


class AppTokens(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - scheme name
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: uuid.UUID


class AppUser(ApiModel):
    id: uuid.UUID
    telegram_id: int
    display_name: str
    username: str | None
    language: str
    referral_code: str
    photo_url: str | None


class AppLinkPollResponse(ApiModel):
    #: pending | approved | denied | expired. A request whose tokens were
    #: already collected reads as expired.
    status: AppLoginStatus
    tokens: AppTokens | None = None
    user: AppUser | None = None


@router.post(
    "/link/start",
    response_model=AppLinkStartResponse,
    summary="Ask to be signed in from the bot",
)
async def start(
    payload: AppLinkStartRequest, container: ContainerDep, context: ContextDep
) -> AppLinkStartResponse:
    bot_username = container.settings.telegram.bot_username.strip().lstrip("@")
    if not bot_username:
        # A link to no bot would leave the customer staring at Telegram's
        # "username not found". Say it is switched off instead.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="App sign-in is not configured."
        )

    async with container.unit_of_work() as uow:
        started = await build_scope(container, uow.session).app_link_login.start(
            device_id=payload.device_id,
            device_name=payload.device_name,
            platform=payload.platform,
            app_version=payload.app_version,
            context=context,
        )
        await uow.commit()

    return AppLinkStartResponse(
        request_id=started.request_id,
        poll_token=started.poll_token,
        deep_link=f"https://t.me/{bot_username}?start={START_PARAM_PREFIX}{started.code}",
        expires_in=started.expires_in_seconds,
    )


@router.post(
    "/link/poll",
    response_model=AppLinkPollResponse,
    summary="Wait for the customer's decision; collect the tokens once approved",
)
async def poll(
    payload: AppLinkPollRequest, container: ContainerDep, context: ContextDep
) -> AppLinkPollResponse:
    deadline = time.monotonic() + (POLL_WAIT_SECONDS if payload.wait else 0.0)
    while True:
        # A fresh transaction per look: a request-scoped one would pin a pooled
        # connection for the whole wait, and a few dozen phones signing in at
        # once would exhaust the pool.
        async with container.unit_of_work() as uow:
            outcome = await build_scope(container, uow.session).app_link_login.poll(
                payload.poll_token, context=context
            )
            await uow.commit()
        if outcome.status is not AppLoginStatus.PENDING or time.monotonic() >= deadline:
            break
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    result = outcome.result
    if result is None or result.user is None:
        return AppLinkPollResponse(status=outcome.status)
    return AppLinkPollResponse(
        status=outcome.status, tokens=_app_tokens(result), user=_app_user(result)
    )


class AppPasswordRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    #: Up to 1 KiB accepted so an over-long password is a plain "wrong
    #: password" rather than a 422 that tells a guesser the limit; the use
    #: case never hashes more than 128 characters.
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(default="", max_length=64)
    platform: str = Field(default="android", max_length=16)
    app_version: str = Field(default="", max_length=32)


class AppPasswordResponse(ApiModel):
    tokens: AppTokens
    user: AppUser


@router.post(
    "/password",
    response_model=AppPasswordResponse,
    summary="Sign in with the username and password set in the bot",
    responses={
        401: {"description": "Unknown username or wrong password (not told apart)"},
        429: {"description": "Too many attempts for this username or network"},
    },
)
async def password_login(
    payload: AppPasswordRequest, scope: ScopeDep, context: ContextDep
) -> AppPasswordResponse:
    result = await scope.app_password_login.login(
        username=payload.username,
        password=payload.password,
        device=AppLoginDevice(
            name=payload.device_name, platform=payload.platform, app_version=payload.app_version
        ),
        context=context,
    )
    return AppPasswordResponse(tokens=_app_tokens(result), user=_app_user(result))


def _app_tokens(result: AuthenticationResult) -> AppTokens:
    return AppTokens(
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        access_expires_at=result.tokens.access_expires_at,
        refresh_expires_at=result.tokens.refresh_expires_at,
        session_id=result.tokens.session_id,
    )


def _app_user(result: AuthenticationResult) -> AppUser:
    user = result.user
    if user is None:  # pragma: no cover - customer logins always carry a profile
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR)
    return AppUser(
        id=user.id,
        telegram_id=user.telegram_id,
        display_name=user.display_name,
        username=user.username,
        language=user.language.value,
        referral_code=user.referral_code,
        photo_url=user.photo_url,
    )
