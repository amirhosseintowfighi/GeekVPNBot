"""Downloads for the bot and Mini App, and the announcement of a new version."""

from __future__ import annotations

import pytest

from geekvpn.entrypoints.worker import is_news
from geekvpn.infrastructure.app_release import AppRelease, ReleaseApk
from geekvpn.infrastructure.client_downloads import (
    ClientDownload,
    android_download,
    windows_download,
)
from geekvpn.infrastructure.desktop_release import DesktopPackage, DesktopRelease
from geekvpn.presentation.bot.ui.release_notice import render_release_notice

pytestmark = pytest.mark.unit


def _apk(abi: str) -> ReleaseApk:
    return ReleaseApk(
        abi=abi,
        file_name=f"GeekVPN_1.4.0_{abi}.apk",
        url=f"https://dl/{abi}.apk",
        sha256=None,
        size_bytes=1,
    )


def test_the_android_link_is_the_apk_that_installs_on_any_phone() -> None:
    release = AppRelease(
        version_name="1.4.0",
        notes="",
        published_at=None,
        apks=(_apk("arm64-v8a"), _apk("universal"), _apk("x86")),
    )
    found = android_download(release, repo="geek/android")
    assert found == ClientDownload("android", "1.4.0", "https://dl/universal.apk")


def test_without_a_release_the_link_is_the_releases_page() -> None:
    found = android_download(None, repo="geek/android")
    assert found is not None and found.version is None
    assert found.url == "https://github.com/geek/android/releases/latest"


def test_a_platform_with_no_repository_offers_no_link() -> None:
    assert windows_download(None, repo="") is None


def test_the_windows_link_is_the_installer() -> None:
    release = DesktopRelease(
        version="2.1.0",
        notes="",
        pub_date=None,
        platforms={
            "darwin-aarch64": DesktopPackage(url="https://dl/mac.tar.gz", signature="s"),
            "windows-x86_64": DesktopPackage(url="https://dl/setup.exe", signature="s"),
        },
    )
    assert windows_download(release, repo="geek/desktop") == ClientDownload(
        "windows", "2.1.0", "https://dl/setup.exe"
    )


@pytest.mark.parametrize(
    ("seen", "version", "news"),
    [
        (None, "1.4.0", False),  # first sight: whatever is current, not news
        ("1.3.0", "1.4.0", True),
        ("1.4.0", "1.4.0", False),
        ("1.5.0", "1.4.0", False),  # a pulled release is not an update
    ],
)
def test_only_a_newer_version_is_announced(seen: str | None, version: str, news: bool) -> None:
    assert is_news(ClientDownload("android", version, "https://x"), seen) is news


def test_the_announcement_carries_the_version_and_a_working_link() -> None:
    title, body = render_release_notice(
        ClientDownload("android", "1.4.0", "https://dl/a.apk?x=1&y=2")
    )
    assert "اندروید" in title
    assert "1.4.0" in body
    assert 'href="https://dl/a.apk?x=1&amp;y=2"' in body
