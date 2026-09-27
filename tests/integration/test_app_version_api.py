"""`GET /api/app/version`: public, and quiet until a repository is configured."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.presentation.api.app import create_app
from tests.conftest import build_test_container

pytestmark = pytest.mark.integration

VERSION = "/api/app/version"


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_updates_are_off_until_a_repository_is_configured(api: TestClient) -> None:
    response = api.get(VERSION)

    assert response.status_code == 200
    assert response.json() == {"latest": None, "minVersion": ""}


def test_the_minimum_version_is_passed_on_without_a_session(
    monkeypatch: pytest.MonkeyPatch, settings: object
) -> None:
    monkeypatch.setenv("APP_RELEASE__MIN_VERSION", " 1.2.0 ")
    get_settings.cache_clear()
    container = build_test_container(get_settings())
    with TestClient(create_app(container=container), raise_server_exceptions=False) as client:
        response = client.get(VERSION)

    assert response.status_code == 200
    assert response.json()["minVersion"] == "1.2.0"
