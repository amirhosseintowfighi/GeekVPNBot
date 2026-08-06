"""Customer authentication endpoints.

Why the tokens are returned in the body and not set as cookies: the primary
clients are a Telegram Mini App and a bot, neither of which is a same-site
browser context. A future web dashboard can layer a cookie-setting endpoint on
top of exactly the same use cases.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from geekvpn.application.identity.dto import AuthenticationResult, TokenPair
from geekvpn.domain.identity.session import RevocationReason
from geekvpn.presentation.api.schemas_auth import (
    MessageResponse,
    MiniAppLoginRequest,
    RefreshRequest,
    SessionResponse,
    TokenResponse,
    UserLoginResponse,
    UserResponse,
    WidgetLoginRequest,
)
from geekvpn.presentation.api.security import ContextDep, CurrentUser, ScopeDep

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/telegram/mini-app",
    response_model=UserLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Sign in with Telegram Mini App initData",
)
async def login_mini_app(
    payload: MiniAppLoginRequest, scope: ScopeDep, context: ContextDep
) -> UserLoginResponse:
    result = await scope.authenticate_telegram.from_mini_app(payload.init_data, context=context)
    return _user_login_response(result)


@router.post(
    "/telegram/widget",
    response_model=UserLoginResponse,
    summary="Sign in with the Telegram Login Widget",
)
async def login_widget(
    payload: WidgetLoginRequest, scope: ScopeDep, context: ContextDep
) -> UserLoginResponse:
    result = await scope.authenticate_telegram.from_login_widget(
        payload.model_dump(exclude_none=True), context=context
    )
    return _user_login_response(result)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new token pair",
    responses={401: {"description": "Invalid, expired, or already-used refresh token"}},
)
async def refresh(payload: RefreshRequest, scope: ScopeDep, context: ContextDep) -> TokenResponse:
    """Works for customers and admins alike - the token identifies the subject."""
    outcome = await scope.sessions.rotate(
        refresh_token=payload.refresh_token,
        context=context,
        role_resolver=scope.resolve_role,
    )
    return _tokens(outcome.tokens)


@router.post("/logout", response_model=MessageResponse, summary="End the current session")
async def logout(subject: CurrentUser, scope: ScopeDep) -> MessageResponse:
    await scope.sessions.revoke(subject.session_id, reason=RevocationReason.LOGOUT)
    return MessageResponse(message="Signed out.")


@router.post(
    "/logout-all",
    response_model=MessageResponse,
    summary="End every session on every device",
)
async def logout_all(subject: CurrentUser, scope: ScopeDep) -> MessageResponse:
    count = await scope.sessions.revoke_all(
        subject_type=subject.subject_type,
        subject_id=subject.subject_id,
        reason=RevocationReason.LOGOUT_ALL,
    )
    return MessageResponse(message=f"Signed out of {count} session(s).")


@router.get("/me", response_model=UserResponse, summary="The signed-in customer")
async def me(subject: CurrentUser, scope: ScopeDep) -> UserResponse:
    from geekvpn.domain.base.errors import NotFoundError

    user = await scope.users.get(subject.subject_id)
    if user is None:  # pragma: no cover - token proves the user existed
        raise NotFoundError("Account not found.")
    return UserResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        display_name=user.display_name,
        username=user.username,
        language=user.language.value,
        status=user.status.value,
        referral_code=user.referral_code,
        is_premium=user.is_premium,
        photo_url=user.photo_url,
        created_at=user.created_at,
    )


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="Active devices for the signed-in customer",
)
async def list_sessions(subject: CurrentUser, scope: ScopeDep) -> list[SessionResponse]:
    now = scope.container.clock.now()
    sessions = await scope.session_repository.list_active_for_subject(
        subject.subject_id, subject_type=subject.subject_type, now=now
    )
    return [
        SessionResponse(
            id=session.id,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            ip=session.device.ip,
            user_agent=session.device.user_agent,
            device_label=session.device.label,
            is_current=session.id == subject.session_id,
        )
        for session in sessions
    ]


def _tokens(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
        session_id=pair.session_id,
    )


def _user_login_response(result: AuthenticationResult) -> UserLoginResponse:
    assert result.user is not None  # noqa: S101 - guaranteed by the use case
    return UserLoginResponse(
        tokens=_tokens(result.tokens),
        user=UserResponse(
            id=result.user.id,
            telegram_id=result.user.telegram_id,
            display_name=result.user.display_name,
            username=result.user.username,
            language=result.user.language.value,
            status=result.user.status,
            referral_code=result.user.referral_code,
            is_premium=result.user.is_premium,
            photo_url=result.user.photo_url,
            created_at=result.user.created_at,
        ),
        is_new_user=result.is_new_user,
    )
