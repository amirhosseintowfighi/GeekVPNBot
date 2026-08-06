"""Cross-cutting HTTP behaviour: correlation ids and problem-details errors."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.domain.base.errors import ConflictError, NotFoundError
from geekvpn.infrastructure.logging.context import CORRELATION_ID_HEADER

pytestmark = pytest.mark.integration


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.headers[CORRELATION_ID_HEADER]


def test_incoming_correlation_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health/live", headers={CORRELATION_ID_HEADER: "from-nginx"})

    assert response.headers[CORRELATION_ID_HEADER] == "from-nginx"


def test_unknown_route_returns_problem_details(client: TestClient) -> None:
    response = client.get("/api/v1/definitely-not-here")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["instance"] == "/api/v1/definitely-not-here"


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_title"),
    [
        (NotFoundError("missing"), 404, "not_found"),
        (ConflictError("already exists"), 409, "conflict"),
    ],
)
def test_domain_errors_map_to_http_status(
    app: FastAPI, error: Exception, expected_status: int, expected_title: str
) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise error

    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == expected_status
    body = response.json()
    assert body["title"] == expected_title
    assert body["correlation_id"]


def test_unhandled_exception_does_not_leak_internals(app: FastAPI) -> None:
    @app.get("/explode")
    async def explode() -> None:
        raise ZeroDivisionError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/explode")

    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["title"] == "internal_error"
