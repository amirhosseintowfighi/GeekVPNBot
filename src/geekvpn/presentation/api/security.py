"""Authentication and authorisation dependencies.

The chain for a protected endpoint:

    Bearer header -> JWT verified -> revocation list checked -> subject built
    -> required permissions asserted (and any denial audited)

The expensive parts (database, Argon2) are not in this path. A normal
authenticated request costs one HMAC verification and one Redis GET pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from geekvpn.application.identity.dto import RequestContext
from geekvpn.domain.base.errors import AuthenticationError
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.errors import MissingPermissionError, SessionRevokedError
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.identity.session import AuthenticatedSubject
from geekvpn.infrastructure.di.scope import RequestScope, build_scope
from geekvpn.infrastructure.security.ip_allowlist import (
    FORWARDED_FOR_HEADER,
    REAL_IP_HEADER,
    client_ip,
)
from geekvpn.presentation.api.dependencies import ContainerDep, UnitOfWorkDep

#: `auto_error=False` so a missing header raises our own problem-details 401
#: instead of FastAPI's bare JSON.
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")

#: Where the admin panel's session lives. The panel and this API are served
#: from the same origin, so the token never has to exist in JavaScript.
ADMIN_ACCESS_COOKIE = "geekvpn_admin_access"
ADMIN_REFRESH_COOKIE = "geekvpn_admin_refresh"


async def get_scope(container: ContainerDep, uow: UnitOfWorkDep) -> AsyncIterator[RequestScope]:
    """Request-scoped service graph, sharing the request's transaction."""
    yield build_scope(container, uow.session)


ScopeDep = Annotated[RequestScope, Depends(get_scope)]


def request_context(request: Request, container: ContainerDep) -> RequestContext:
    """Where this call came from.

    The address is resolved by `client_ip`, counting from the *right* of
    `X-Forwarded-For` by the number of proxies we operate. Reading the leftmost
    entry - as this used to - meant the caller chose its own address, and that
    address then decided the admin IP allowlist, the login rate-limit key and
    what every audit row recorded.
    """
    return RequestContext(
        ip=client_ip(
            remote_addr=request.client.host if request.client else None,
            forwarded_for=request.headers.get(FORWARDED_FOR_HEADER),
            real_ip=request.headers.get(REAL_IP_HEADER),
            trusted_proxy_count=container.settings.security.trusted_proxy_count,
        ),
        user_agent=request.headers.get("User-Agent"),
        device_label=request.headers.get("X-Device-Label"),
    )


ContextDep = Annotated[RequestContext, Depends(request_context)]


async def get_current_subject(
    request: Request,
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedSubject:
    # Header first, cookie second. Scripts, the bot and the Mini App all send a
    # Bearer header; the admin panel is a browser on the same origin and sends
    # an httpOnly cookie instead, which is why it could never authenticate
    # against a header-only check no matter how correctly it signed in.
    token = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get(ADMIN_ACCESS_COOKIE)
    if not token:
        raise AuthenticationError("An Authorization: Bearer header is required.")

    claims = container.access_tokens.decode(token)

    if await container.revocations.is_revoked(
        session_id=claims.session_id,
        subject_id=claims.subject_id,
        issued_at=claims.issued_at,
    ):
        raise SessionRevokedError()

    return AuthenticatedSubject(
        subject_type=claims.subject_type,
        subject_id=claims.subject_id,
        session_id=claims.session_id,
        role=claims.role,
        permissions=frozenset(claims.permissions),
    )


CurrentSubject = Annotated[AuthenticatedSubject, Depends(get_current_subject)]


async def get_current_user(subject: CurrentSubject) -> AuthenticatedSubject:
    """Reject an admin token on a customer endpoint, and vice versa.

    An admin token must not be usable to call customer endpoints: the two have
    different lifetimes and different threat models, and mixing them makes
    "who performed this action?" unanswerable.
    """
    if subject.subject_type is not SubjectType.USER:
        raise MissingPermissionError("This endpoint is for customer accounts.")
    return subject


CurrentUser = Annotated[AuthenticatedSubject, Depends(get_current_user)]


async def get_current_admin(subject: CurrentSubject) -> AuthenticatedSubject:
    if subject.subject_type is not SubjectType.ADMIN:
        raise MissingPermissionError("This endpoint is for administrator accounts.")
    return subject


CurrentAdmin = Annotated[AuthenticatedSubject, Depends(get_current_admin)]


def requires(
    *permissions: Permission, require_all: bool = True
) -> Callable[..., Awaitable[AuthenticatedSubject]]:
    """Dependency factory guarding an endpoint with permissions.

        @router.get("/users", dependencies=[Depends(requires(Permission.USERS_READ))])

    Denials are audited, not silently returned - see `AuthorizationService`.
    """

    async def dependency(
        request: Request,
        subject: CurrentAdmin,
        scope: ScopeDep,
    ) -> AuthenticatedSubject:
        await scope.authorization.authorize(
            subject,
            *permissions,
            require_all=require_all,
            resource=request.url.path,
        )
        return subject

    return dependency
