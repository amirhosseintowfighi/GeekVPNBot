"""`GET /api/miniapp/apps`: the bot's download and tutorial screen, as data."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.infrastructure.config.settings import AppReleaseSettings
from geekvpn.presentation.api.routers.miniapp import apps

pytestmark = pytest.mark.unit


class _Settings:
    def __init__(self, tutorials: dict[str, Any]) -> None:
        self._tutorials = tutorials

    async def get(self, definition: Any) -> Any:
        return self._tutorials


def _scope(*, android_repo: str, tutorials: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        container=SimpleNamespace(
            settings=SimpleNamespace(app_release=AppReleaseSettings(github_repo=android_repo)),
            cache=None,
        ),
        settings_service=_Settings(tutorials),
    )


async def test_tutorials_come_in_device_order_with_their_text() -> None:
    scope = _scope(
        android_repo="",
        tutorials={
            "windows": {"kind": "video", "file_id": "V", "text": "ویندوز"},
            "android": {"kind": "text", "text": "اندروید"},
        },
    )
    answer = await apps(user=object(), scope=scope)  # type: ignore[arg-type]
    assert [t["device"] for t in answer["tutorials"]] == ["android", "windows"]
    assert answer["tutorials"][1]["kind"] == "video"
    assert answer["downloads"] == []


async def test_an_unreachable_release_falls_back_to_the_releases_page() -> None:
    class _Cache:
        async def get(self, key: str) -> str | None:
            return "none"  # GitHub said there is no release yet

        async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
            return None

    scope = _scope(android_repo="geek/android", tutorials={})
    scope.container.cache = _Cache()
    answer = await apps(user=object(), scope=scope)  # type: ignore[arg-type]
    assert answer["downloads"][0]["url"] == "https://github.com/geek/android/releases/latest"
