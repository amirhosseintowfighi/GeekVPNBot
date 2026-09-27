"""Reading the Android app's latest release from GitHub."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from geekvpn.infrastructure.app_release import (
    CACHE_KEY,
    GithubReleaseSource,
    abi_of,
    parse_release,
)

DIGEST = "a" * 64


def _asset(name: str, *, digest: str | None = f"sha256:{DIGEST}") -> dict[str, Any]:
    return {
        "name": name,
        "size": 31_000_000,
        "browser_download_url": f"https://github.com/o/r/releases/download/v1.2.0/{name}",
        "digest": digest,
    }


RELEASE: dict[str, Any] = {
    "tag_name": "v1.2.0",
    "body": "رفع مشکل اتصال",
    "published_at": "2026-09-27T10:00:00Z",
    "assets": [
        _asset("GeekVPN_1.2.0_universal.apk"),
        _asset("GeekVPN_1.2.0_arm64-v8a.apk"),
        _asset("mapping.txt"),
        _asset("GeekVPN_1.2.0_armeabi-v7a.apk", digest=None),
    ],
}


class DictCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.values[key] = value


def _source(
    handler: Any, cache: DictCache | None = None, *, repo: str = "o/r", mirror: str = ""
) -> GithubReleaseSource:
    return GithubReleaseSource(
        repo=repo,
        cache=cache or DictCache(),
        cache_seconds=600,
        mirror_base_url=mirror,
        transport=httpx.MockTransport(handler),
    )


def test_the_abi_is_read_from_the_file_name_ci_gives_the_apk() -> None:
    assert abi_of("GeekVPN_1.2.0_arm64-v8a.apk") == "arm64-v8a"
    assert abi_of("GeekVPN_1.2.0_universal.apk") == "universal"
    assert abi_of("mapping.txt") is None
    assert abi_of("GeekVPN_1.2.0_mips.apk") is None


def test_a_release_lists_its_apks_with_their_digests_and_nothing_else() -> None:
    release = parse_release(RELEASE)

    assert release is not None
    assert release.version_name == "1.2.0"
    assert [apk.abi for apk in release.apks] == ["arm64-v8a", "armeabi-v7a", "universal"]
    by_abi = {apk.abi: apk for apk in release.apks}
    assert by_abi["arm64-v8a"].sha256 == DIGEST
    # No digest reported: none is invented.
    assert by_abi["armeabi-v7a"].sha256 is None


def test_a_mirror_replaces_the_download_host_but_keeps_the_file_name() -> None:
    release = parse_release(RELEASE, mirror_base_url="https://dl.example.ir/geekvpn/")

    assert release is not None
    assert release.apks[0].url == "https://dl.example.ir/geekvpn/GeekVPN_1.2.0_arm64-v8a.apk"


def test_a_release_without_an_apk_is_no_release() -> None:
    assert parse_release({**RELEASE, "assets": [_asset("notes.md")]}) is None


@pytest.mark.asyncio
async def test_the_answer_is_cached_so_github_is_asked_once() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=RELEASE)

    cache = DictCache()
    source = _source(handler, cache)
    first = await source.latest()
    second = await source.latest()

    assert calls == ["https://api.github.com/repos/o/r/releases/latest"]
    assert first == second
    assert first is not None and first.version_name == "1.2.0"


@pytest.mark.asyncio
async def test_a_repository_with_no_release_yet_answers_none_and_remembers_it() -> None:
    cache = DictCache()
    source = _source(lambda _: httpx.Response(404, json={"message": "Not Found"}), cache)

    assert await source.latest() is None
    assert cache.values[CACHE_KEY] == "none"


@pytest.mark.asyncio
async def test_github_failing_is_not_cached() -> None:
    cache = DictCache()

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    assert await _source(fail, cache).latest() is None
    assert await _source(lambda _: httpx.Response(502), cache).latest() is None
    assert CACHE_KEY not in cache.values


@pytest.mark.asyncio
async def test_no_repository_configured_means_no_request_at_all() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("GitHub must not be asked")

    assert await _source(refuse, repo="").latest() is None


@pytest.mark.asyncio
async def test_a_cached_release_reads_back_the_same() -> None:
    cache = DictCache()
    fresh = await _source(lambda _: httpx.Response(200, json=RELEASE), cache).latest()
    assert json.loads(cache.values[CACHE_KEY])["version_name"] == "1.2.0"

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("served from the cache")

    assert await _source(refuse, cache).latest() == fresh
