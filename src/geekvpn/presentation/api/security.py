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
from geekvpn.presentation.api.dependencies import ContainerDep, UnitOfWorkDep

#: `auto_error=False` so a missing header raises our own problem-details 401
#: instead of FastAPI's bare JSON.
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


async def get_scope(container: ContainerDep, uow: UnitOfWorkDep) -> AsyncIterator[RequestScope]:
    """Request-scoped service graph, sharing the request's transaction."""
    yield build_scope(container, uow.session)


ScopeDep = Annotated[RequestScope, Depends(get_scope)]


def request_context(request: Request) -> RequestContext:
    """Where this call came from.

    `X-Forwarded-For` is trusted only because Nginx overwrites it at the edge;
    the leftmost entry is the client. Never trust it if the app is ever exposed
    directly.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else None
    if not ip and request.client:
        ip = request.client.host
    return RequestContext(
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
        device_label=request.headers.get("X-Device-Label"),
    )


ContextDep = Annotated[RequestContext, Depends(request_context)]


async def get_current_subject(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedSubject:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("An Authorization: Bearer header is required.")

    claims = container.access_tokens.decode(credentials.credentials)

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
