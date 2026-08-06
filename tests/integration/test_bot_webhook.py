"""The webhook must reject anything that is not signed by Telegram."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.presentation.bot.app import SECRET_HEADER, create_bot_app
from tests.conftest import TEST_BOT_TOKEN, TEST_SECRET, build_test_container

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def bot_client() -> Iterator[TestClient]:
    """One app for the whole module.

    Handler routers are module-level singletons and aiogram refuses to attach a
    router to a second dispatcher, so a process can only ever hold one bot app.
    Building it per test raises `Router is already attached`.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("APP__ENV", "local")
    patch.setenv("AUTH__JWT_SECRET_KEY", TEST_SECRET)
    patch.setenv("TELEGRAM__BOT_TOKEN", TEST_BOT_TOKEN)
    get_settings.cache_clear()
    settings = get_settings()

    with TestClient(create_bot_app(settings, container=build_test_container(settings))) as client:
        yield client

    patch.undo()
    get_settings.cache_clear()


def test_webhook_rejects_a_missing_secret(bot_client: TestClient, settings: Settings) -> None:
    response = bot_client.post(settings.telegram.webhook_path, json={"update_id": 1})

    assert response.status_code == 403


def test_webhook_rejects_a_wrong_secret(bot_client: TestClient, settings: Settings) -> None:
    response = bot_client.post(
        settings.telegram.webhook_path,
        json={"update_id": 1},
        headers={SECRET_HEADER: "not-the-secret"},
    )

    assert response.status_code == 403


def test_bot_exposes_its_own_liveness(bot_client: TestClient) -> None:
    response = bot_client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["service"].endswith("-bot")
