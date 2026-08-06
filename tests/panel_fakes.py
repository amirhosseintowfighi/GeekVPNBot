"""Test doubles for panel adapters.

`FakePanelServer` is a tiny routing HTTP double built on `httpx.MockTransport`,
so adapters are exercised through their real HTTP code path - retries, error
translation, envelope parsing and all. Mocking the adapter's own methods would
test nothing; mocking the transport tests everything below it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx

PANEL_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")

Handler = Callable[[httpx.Request], httpx.Response]


class FakePanelServer:
    """Routes `(METHOD, path)` to canned responses and records every call."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], Handler] = {}
        self._prefix_routes: list[tuple[str, str, Handler]] = []
        self.calls: list[httpx.Request] = []

    def route(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        status: int = 200,
        headers: dict[str, str] | None = None,
        handler: Handler | None = None,
    ) -> FakePanelServer:
        self._routes[(method.upper(), path)] = handler or (
            lambda _r: httpx.Response(status, json=json, headers=headers)
        )
        return self

    def prefix(
        self,
        method: str,
        path_prefix: str,
        *,
        json: Any = None,
        status: int = 200,
        handler: Handler | None = None,
    ) -> FakePanelServer:
        """Match any path starting with `path_prefix`.

        Needed for endpoints that embed an id, e.g. `/api/user/{username}`.
        """
        self._prefix_routes.append(
            (
                method.upper(),
                path_prefix,
                handler or (lambda _r: httpx.Response(status, json=json)),
            )
        )
        return self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method.upper(), request.url.path)
        if key in self._routes:
            return self._routes[key](request)
        for method, prefix, handler in self._prefix_routes:
            if request.method.upper() == method and request.url.path.startswith(prefix):
                return handler(request)
        return httpx.Response(404, json={"detail": "no route", "path": request.url.path})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self, method: str | None = None) -> list[str]:
        return [
            c.url.path for c in self.calls if method is None or c.method.upper() == method.upper()
        ]

    def count(self, method: str, path: str) -> int:
        return sum(
            1 for c in self.calls if c.method.upper() == method.upper() and c.url.path == path
        )


def token_route(server: FakePanelServer, path: str) -> FakePanelServer:
    """Install a standard OAuth2 token endpoint."""
    return server.route("POST", path, json={"access_token": "test-token", "token_type": "bearer"})
