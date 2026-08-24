"""RFC 9457 problem details.

Every error response in this API has the same shape, whatever caused it:

    {
      "type": "about:blank",
      "title": "not_found",
      "status": 404,
      "detail": "...",
      "instance": "/api/v1/...",
      "correlation_id": "..."
    }

Why: clients (bot, Mini App, admin) parse one shape, and support can find any
reported failure in the logs by its correlation id.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from geekvpn.domain.base.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ValidationError,
)
from geekvpn.domain.catalog.errors import CatalogError
from geekvpn.domain.panels.errors import PanelError
from geekvpn.infrastructure.logging.context import get_correlation_id
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.api.text_fa import user_message

logger = get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"

#: Order matters: the most specific type must come first, because the lookup
#: is an `isinstance` walk and several of these are related by inheritance.
_DOMAIN_STATUS_MAP: tuple[tuple[type[DomainError], int], ...] = (
    (ValidationError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
    (RateLimitedError, status.HTTP_429_TOO_MANY_REQUESTS),
    # A panel failure is an upstream failure, not the caller's mistake.
    # 502 keeps it out of the client-error rate that alerting watches and
    # tells the Mini App to say 'try again shortly' rather than 'fix your
    # input'.
    (PanelError, status.HTTP_502_BAD_GATEWAY),
    # Last on purpose: CatalogValidationError and CatalogConflict still
    # resolve to 422 and 409 through their own base classes above. Only a
    # bare CatalogError (a purchasability or promotion refusal) lands here.
    (CatalogError, status.HTTP_409_CONFLICT),
)


def problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        # `detail` is English and written for whoever reads the logs. Both
        # frontends render this field instead, and until it existed they had
        # nothing to render but their own generic copy - which on the sign-in
        # screen told an operator with a wrong password that their session had
        # expired.
        "message_fa": user_message(title, detail),
        "instance": instance,
        "correlation_id": get_correlation_id(),
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


def _status_for(exc: DomainError) -> int:
    for error_type, code in _DOMAIN_STATUS_MAP:
        if isinstance(exc, error_type):
            return code
    return status.HTTP_400_BAD_REQUEST


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        status_code = _status_for(exc)
        logger.info("http.domain_error", code=exc.code, path=request.url.path)
        headers = (
            # RFC 9110 requires this on a 401.
            {"WWW-Authenticate": 'Bearer realm="geekvpn"'}
            if status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        return problem_response(
            status_code=status_code,
            title=exc.code,
            detail=exc.message,
            instance=request.url.path,
            extra={"details": exc.details} if exc.details else None,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Which field, in the log, not only in the response body.
        #
        # A 422 read from `docker logs` used to say nothing but "validation
        # error" on a path, so diagnosing one meant asking whoever hit it to
        # open devtools and read the response - and every guess in between was
        # a wasted round trip. The location and the reason are enough to name
        # the field; the submitted value is deliberately left out, because a
        # rejected login body holds a password.
        logger.info(
            "http.validation_failed",
            path=request.url.path,
            fields=[
                {"loc": ".".join(str(part) for part in error["loc"]), "type": error["type"]}
                for error in exc.errors()
            ],
        )
        return problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="validation_error",
            detail="Request validation failed.",
            instance=request.url.path,
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(
            status_code=exc.status_code,
            title=str(exc.detail),
            detail=str(exc.detail),
            instance=request.url.path,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback, return nothing internal to the caller.
        logger.exception("http.unhandled_error", path=request.url.path)
        return problem_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="internal_error",
            detail="An unexpected error occurred. Support can trace it by correlation id.",
            instance=request.url.path,
        )
