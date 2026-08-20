"""Administrator authentication.

The TOTP replay guard lives here rather than in the TOTP service because it
needs Redis, and a pure RFC 6238 implementation should stay pure. A code is
valid for a whole 30-second step, so without this a shoulder-surfed code could
be used twice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from geekvpn.domain.identity.errors import TwoFactorInvalidError
from geekvpn.domain.identity.session import RevocationReason
from geekvpn.presentation.api.schemas_auth import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminResponse,
    MessageResponse,
    TokenResponse,
)
from geekvpn.presentation.api.security import (
    ADMIN_ACCESS_COOKIE,
    ADMIN_REFRESH_COOKIE,
    ContextDep,
    CurrentAdmin,
    ScopeDep,
)

router = APIRouter(prefix="/admin/auth", tags=["admin-authentication"])

TOTP_REPLAY_TTL_SECONDS = 90


def _set_session_cookies(response: Response, tokens: TokenResponse) -> None:
    """Put the pair in httpOnly cookies as well as the body.

    The admin panel is served from the same origin as this API - nginx routes
    /api/ on the admin host to the backend - so a cookie needs no CORS and no
    token in JavaScript for an injected script or a browser extension to read.
    That is the transport the panel's client was written against; it sends
    `credentials: 'include'` and no Authorization header.

    SameSite=Strict is what stands in for a CSRF token: a cross-site request
    never carries these cookies, so a forged form cannot act as an operator.
    """
    for name, value, expires in (
        (ADMIN_ACCESS_COOKIE, tokens.access_token, tokens.access_expires_at),
        (ADMIN_REFRESH_COOKIE, tokens.refresh_token, tokens.refresh_expires_at),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max(0, int((expires - datetime.now(UTC)).total_seconds())),
            httponly=True,
            secure=True,
            samesite="strict",
            path="/api/",
        )


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Administrator password login",
    responses={
        401: {"description": "Invalid credentials, locked account, or missing 2FA code"},
        403: {"description": "Source IP is not on the allow-list"},
    },
)
async def login(
    payload: AdminLoginRequest, response: Response, scope: ScopeDep, context: ContextDep
) -> AdminLoginResponse:
    if payload.totp_code:
        await _reject_replayed_totp(scope, payload.username, payload.totp_code)

    result = await scope.authenticate_admin.execute(
        username=payload.username,
        password=payload.password,
        totp_code=payload.totp_code,
        context=context,
    )
    assert result.admin is not None  # noqa: S101 - guaranteed by the use case
    tokens = TokenResponse(
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        access_expires_at=result.tokens.access_expires_at,
        refresh_expires_at=result.tokens.refresh_expires_at,
        session_id=result.tokens.session_id,
    )
    _set_session_cookies(response, tokens)
    return AdminLoginResponse(
        tokens=tokens,
        admin=AdminResponse(
            id=result.admin.id,
            username=result.admin.username,
            role=result.admin.role,
            permissions=list(result.admin.permissions),
            is_totp_enabled=result.admin.is_totp_enabled,
            last_login_at=result.admin.last_login_at,
        ),
    )


@router.post(
    "/sign-out",
    response_model=MessageResponse,
    summary="End the current administrator session",
)
async def sign_out(subject: CurrentAdmin, response: Response, scope: ScopeDep) -> MessageResponse:
    """Revoke the session *and* clear the cookies.

    Clearing the cookies alone would leave a token that still verifies for
    anyone who captured it, so the revocation is the part that matters and the
    cookies are housekeeping.
    """
    await scope.sessions.revoke(subject.session_id, reason=RevocationReason.LOGOUT)
    for name in (ADMIN_ACCESS_COOKIE, ADMIN_REFRESH_COOKIE):
        response.delete_cookie(name, path="/api/", httponly=True, secure=True, samesite="strict")
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=AdminResponse, summary="The signed-in administrator")
async def me(subject: CurrentAdmin, scope: ScopeDep) -> AdminResponse:
    from geekvpn.domain.base.errors import NotFoundError

    admin = await scope.admins.get(subject.subject_id)
    if admin is None:  # pragma: no cover
        raise NotFoundError("Administrator not found.")
    return AdminResponse(
        id=admin.id,
        username=admin.username,
        role=admin.role.value,
        permissions=sorted(p.value for p in admin.permissions),
        is_totp_enabled=admin.is_totp_enabled,
        last_login_at=admin.last_login_at,
    )


async def _reject_replayed_totp(scope: ScopeDep, username: str, code: str) -> None:
    """One TOTP code, one use.

    `add_if_absent` is an atomic SETNX, so two simultaneous logins with the
    same code cannot both pass.
    """
    key = f"totp-used:{username.strip().lower()}:{code}"
    first_use = await scope.container.cache.add_if_absent(
        key, "1", ttl_seconds=TOTP_REPLAY_TTL_SECONDS
    )
    if not first_use:
        raise TwoFactorInvalidError("This code has already been used.")
