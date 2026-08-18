"""The webhook must reject anything that is not signed by Telegram."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geekvpn.infrastructure.config.settings import Settings
from geekvpn.presentation.bot.app import SECRET_HEADER

pytestmark = pytest.mark.integration


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
