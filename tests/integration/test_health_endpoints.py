"""Health endpoint contract.

These run against a real ASGI app with fake dependencies, so they exercise the
middleware stack, the DI wiring and the response schema without needing
Postgres or Redis.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geekvpn.infrastructure.config.settings import Settings
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.api.app import create_app

pytestmark = pytest.mark.integration


def test_liveness_never_touches_dependencies(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readiness_reports_every_dependency(client: TestClient) -> None:
    response = client.get("/health/ready")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert {dep["name"] for dep in body["dependencies"]} == {"postgres", "redis"}


def test_readiness_returns_503_when_a_dependency_is_down(
    settings: Settings, degraded_container: Container
) -> None:
    with TestClient(create_app(settings, container=degraded_container)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    # The degraded container fails every probe, so what matters is that each one
    # is reported by name and carries the reason the probe gave.
    unhealthy = {dep["name"]: dep for dep in body["dependencies"] if not dep["healthy"]}
    assert set(unhealthy) == {"postgres", "redis"}
    assert unhealthy["redis"]["error"] == "unavailable"


def test_service_info_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/info")

    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
