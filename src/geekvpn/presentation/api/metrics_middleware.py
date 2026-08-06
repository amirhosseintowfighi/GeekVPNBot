"""Metrics collection middleware and the scrape endpoint.

Two decisions worth stating, because both are easy to get wrong in a way that
only hurts later:

**Unmatched routes collapse to one label.** After routing, Starlette exposes the
matched route template on the scope. When there is no match — a scanner probing
``/wp-admin``, ``/.env`` and ten thousand other paths — the path label becomes the
literal ``"<unmatched>"``. Templating alone cannot save us there, because those
paths contain no identifiers to collapse, so without this an anonymous attacker
chooses our time series names.

**The scrape endpoint is not exposed at the edge.** Nginx denies ``/metrics``
from outside, and Prometheus reaches it over the internal Docker network.
Metrics are not secret in the way a password is, but they do leak revenue shape,
customer counts and internal path names.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Match

from geekvpn.infrastructure.observability.metrics import (
    CONTENT_TYPE,
    AppMetrics,
    normalise_path,
    status_class,
)

#: Label used for any request that matched no route.
UNMATCHED = "<unmatched>"

#: Paths excluded from metrics. Health probes fire every fifteen seconds per
#: container and would otherwise dominate the request rate graph, hiding real
#: traffic behind a flat line of probes. The scrape endpoint excludes itself for
#: the same reason.
EXCLUDED_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})


def _route_label(request: Request) -> str:
    """Resolve a bounded path label for this request.

    Prefers the matched route template, because ``/api/v1/users/{user_id}`` is
    both bounded and readable. Falls back to a normalised path, then to a single
    bucket for anything unmatched.
    """
    router = request.scope.get("app")
    if router is not None:
        for route in getattr(router, "routes", []):
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
                if path_format:
                    return str(path_format)
    normalised = normalise_path(request.url.path)
    # An unmatched path is attacker-controlled. One bucket for all of it.
    return normalised if normalised.startswith("/api") else UNMATCHED


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records request count, latency and concurrency.

    Registered as the outermost middleware so the latency it measures includes
    every other middleware. Measuring only the handler produces a number that
    disagrees with what the customer experienced, which is the number that
    matters during an incident.
    """

    def __init__(self, app: object, metrics: AppMetrics) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        path = _route_label(request)
        method = request.method
        self._metrics.http_in_flight.inc()
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # An unhandled exception still produced a 500 for the customer, so it
            # must appear in the metrics. Recording only successful responses is
            # how an error-rate graph stays flat through an outage.
            raise
        finally:
            elapsed = time.perf_counter() - started
            self._metrics.http_in_flight.dec()
            self._metrics.http_duration.observe(elapsed, method=method, path=path)
            self._metrics.http_requests.inc(
                method=method, path=path, status=status_class(status_code)
            )


async def metrics_endpoint(request: Request) -> Response:
    """Prometheus scrape target. Reachable only from the internal network."""
    metrics: AppMetrics | None = getattr(request.app.state, "metrics", None)
    if metrics is None:
        # A 503 rather than an empty 200: an empty scrape looks like a healthy
        # application with no traffic, and every alert would stay silent.
        return PlainTextResponse("metrics are not initialised\n", status_code=503)
    return PlainTextResponse(metrics.registry.render(), media_type=CONTENT_TYPE)


__all__ = ["EXCLUDED_PATHS", "UNMATCHED", "MetricsMiddleware", "metrics_endpoint"]
