"""The desktop app's updater manifest, read from its GitHub release."""

from __future__ import annotations

import json
from typing import Any

import httpx

from geekvpn.infrastructure.desktop_release import (
    CACHE_KEY,
    DesktopReleaseSource,
    parse_manifest,
    update_for,
    version_tuple,
)

BASE = "https://github.com/o/d/releases/download/v1.2.0"
MANIFEST: dict[str, Any] = {
    "version": "1.2.0",
    "notes": "- اسکنر سریع‌تر",
    "pub_date": "2026-10-01T10:00:00Z",
    "platforms": {
        "windows-x86_64": {"url": f"{BASE}/GeekVPN_1.2.0_x64-setup.exe", "signature": "sig-win"},
        "windows-x86_64-nsis": {
            "url": f"{BASE}/GeekVPN_1.2.0_x64-setup.exe",
            "signature": "sig-win",
        },
        "windows-x86_64-msi": {
            "url": f"{BASE}/GeekVPN_1.2.0_x64_en-US.msi",
            "signature": "sig-msi",
        },
        "linux-x86_64-deb": {"url": f"{BASE}/GeekVPN_1.2.0_amd64.deb", "signature": "sig-deb"},
        "linux-x86_64": {
            "url": f"{BASE}/GeekVPN_1.2.0_amd64.AppImage",
            "signature": "sig-appimage",
        },
        "darwin-aarch64": {"url": f"{BASE}/GeekVPN_universal.app.tar.gz", "signature": "sig-mac"},
        "broken": {"url": "http://insecure/x", "signature": "s"},
        "unsigned": {"url": f"{BASE}/x", "signature": ""},
    },
}


def _ask(release: Any, **over: str) -> dict[str, Any] | None:
    args = {
        "target": "windows",
        "arch": "x86_64",
        "bundle": "nsis",
        "current_version": "1.1.4",
        "min_version": "",
    }
    args.update(over)
    return update_for(release, **args)  # type: ignore[arg-type]


def test_versions_compare_as_numbers_not_text() -> None:
    assert version_tuple("1.10.0") > version_tuple("1.9.9")  # type: ignore[operator]
    assert version_tuple("v1.2.0-beta.1") == (1, 2, 0)
    assert version_tuple("latest") is None


def test_only_signed_https_packages_are_offered() -> None:
    release = parse_manifest(MANIFEST)

    assert release is not None
    assert "broken" not in release.platforms
    assert "unsigned" not in release.platforms


def test_the_mirror_serves_the_same_file_names() -> None:
    release = parse_manifest(MANIFEST, mirror_base_url="https://dl.example.ir/desktop/")

    assert release is not None
    assert (
        release.platforms["linux-x86_64-deb"].url
        == "https://dl.example.ir/desktop/GeekVPN_1.2.0_amd64.deb"
    )
    # The signature is the release's own: a mirror cannot change what verifies.
    assert release.platforms["linux-x86_64-deb"].signature == "sig-deb"


def test_each_install_gets_its_own_kind_of_package() -> None:
    release = parse_manifest(MANIFEST)

    nsis = _ask(release)
    deb = _ask(release, target="linux", bundle="deb")
    appimage = _ask(release, target="linux", bundle="appimage")
    assert nsis is not None and nsis["signature"] == "sig-win"
    assert deb is not None and deb["url"].endswith(".deb")
    # No `linux-x86_64-appimage` entry: the platform's plain entry is it.
    assert appimage is not None and appimage["url"].endswith(".AppImage")
    assert nsis["version"] == "1.2.0" and nsis["pub_date"] == "2026-10-01T10:00:00Z"


def test_nothing_newer_is_no_update() -> None:
    release = parse_manifest(MANIFEST)

    assert _ask(release, current_version="1.2.0") is None
    assert _ask(release, current_version="1.3.0") is None
    assert _ask(release, target="freebsd") is None
    assert _ask(None) is None
    assert _ask(release, target="../etc") is None


def test_versions_below_the_floor_are_told_to_update() -> None:
    release = parse_manifest(MANIFEST)

    assert _ask(release, min_version="1.2.0")["required"] is True  # type: ignore[index]
    assert _ask(release, current_version="1.1.9", min_version="1.1.0")["required"] is False  # type: ignore[index]


class DictCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.values[key] = value


def _github(manifest: dict[str, Any] | None) -> Any:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/repos/o/d/releases/latest":
            assets = [{"name": "GeekVPN_1.2.0_amd64.deb", "browser_download_url": f"{BASE}/x.deb"}]
            if manifest is not None:
                assets.append(
                    {"name": "latest.json", "browser_download_url": f"{BASE}/latest.json"}
                )
            return httpx.Response(200, json={"tag_name": "v1.2.0", "assets": assets})
        if request.url.path.endswith("/latest.json"):
            return httpx.Response(200, json=manifest)
        return httpx.Response(404)

    return handler, calls


async def test_the_manifest_is_read_once_and_then_from_the_cache() -> None:
    handler, calls = _github(MANIFEST)
    cache = DictCache()
    source = DesktopReleaseSource(
        repo="o/d", cache=cache, cache_seconds=600, transport=httpx.MockTransport(handler)
    )

    first = await source.latest()
    second = await source.latest()

    assert first is not None and second == first
    assert len(calls) == 2
    assert json.loads(cache.values[CACHE_KEY])["version"] == "1.2.0"


async def test_a_release_without_a_signed_manifest_offers_nothing() -> None:
    handler, _ = _github(None)
    source = DesktopReleaseSource(
        repo="o/d", cache=DictCache(), cache_seconds=600, transport=httpx.MockTransport(handler)
    )

    assert await source.latest() is None


async def test_no_repository_means_updates_are_off() -> None:
    source = DesktopReleaseSource(repo="", cache=DictCache(), cache_seconds=600)

    assert await source.latest() is None
