"""An unknown environment key must not take a container down.

One `.env` is shared by the api, bot, worker and migrate containers, and a
blue/green deploy replaces their images at different moments. A key added for a
setting the newer image understands used to crash-loop every container still
running the older one: the root `Settings` ignored unknown keys, but each
nested section forbade them, and it is the section that receives them.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.config.settings import Settings, get_settings

pytestmark = pytest.mark.unit


def test_a_key_no_image_understands_yet_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM__A_SETTING_FROM_A_NEWER_IMAGE", "https://app.example.com")
    get_settings.cache_clear()

    settings = Settings()

    assert not hasattr(settings.telegram, "a_setting_from_a_newer_image")


def test_the_same_holds_for_every_section(monkeypatch: pytest.MonkeyPatch) -> None:
    for prefix in ("APP", "LOGGING", "POSTGRES", "REDIS", "TELEGRAM", "SECURITY", "AUTH"):
        monkeypatch.setenv(f"{prefix}__NOT_A_REAL_SETTING", "x")
    get_settings.cache_clear()

    Settings()
