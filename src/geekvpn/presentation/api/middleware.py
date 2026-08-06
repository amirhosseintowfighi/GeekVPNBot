"""HTTP middleware: correlation ids and structured access logs."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from geekvpn.infrastructure.logging.context import (
    CORRELATION_ID_HEADER,
    bind_correlation_id,
    get_correlation_id,
    reset_correlation_id,
)
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger("http.access")

# Health checks run every few seconds; logging them buries real traffic.
_SILENT_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Adopt the id from the edge (Nginx sets ``X-Request-ID``) or mint one."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(CORRELATION_ID_HEADER)
        token = bind_correlation_id(incoming)
        try:
            response = await call_next(request)
        finally:
            correlation_id = get_correlation_id()
            reset_correlation_id(token)
        if correlation_id:
            response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request. Uvicorn's own access log is disabled."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "http.request.failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise

        if request.url.path not in _SILENT_PATHS:
            logger.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                client=request.client.host if request.client else None,
            )
        return response
