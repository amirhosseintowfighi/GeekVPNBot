"""The Android app's latest release, read from GitHub Releases.

The app's CI publishes a release for every `v*` tag, with one APK per ABI named
`GeekVPN_<version>_<abi>.apk`. This reads the newest one and describes it in
the shape the app needs: a version to compare, and per ABI a URL and the
SHA-256 the app checks before installing.

Cached, because every app asks at start and GitHub allows an unauthenticated
address sixty requests an hour. A failure is not cached: the next request
tries again rather than reporting "no update" for ten minutes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 10.0
CACHE_KEY = "app_release:latest"
#: The file names CI gives the APKs; anything else attached to a release
#: (checksums, mapping files) is not something to install.
KNOWN_ABIS = frozenset({"arm64-v8a", "armeabi-v7a", "x86", "x86_64", "universal"})
#: Cached in place of a release when the repository has none yet, so a quiet
#: repository is not asked again on every app start.
_NO_RELEASE = "none"


@dataclass(frozen=True, slots=True)
class ReleaseApk:
    abi: str
    file_name: str
    url: str
    #: Lowercase hex. None when GitHub did not report a digest for the file;
    #: the app then relies on Android's own signature check alone.
    sha256: str | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class AppRelease:
    #: The tag without its leading `v`: `1.2.0`.
    version_name: str
    notes: str
    published_at: str | None
    apks: tuple[ReleaseApk, ...]


class StringCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...


def abi_of(file_name: str) -> str | None:
    """`GeekVPN_1.2.0_arm64-v8a.apk` -> `arm64-v8a`; None for any other file."""
    if not file_name.endswith(".apk"):
        return None
    abi = file_name.removesuffix(".apk").rsplit("_", 1)[-1]
    return abi if abi in KNOWN_ABIS else None


def parse_release(payload: Mapping[str, Any], *, mirror_base_url: str = "") -> AppRelease | None:
    """GitHub's release JSON as an `AppRelease`, or None if it holds no APK.

    Drafts and prereleases never reach here: `releases/latest` skips both.
    """
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return None
    mirror = mirror_base_url.strip().rstrip("/")
    apks: list[ReleaseApk] = []
    for asset in payload.get("assets") or ():
        name = str(asset.get("name") or "")
        abi = abi_of(name)
        if abi is None:
            continue
        digest = str(asset.get("digest") or "")
        sha256 = digest.removeprefix("sha256:").lower() if digest.startswith("sha256:") else None
        url = f"{mirror}/{name}" if mirror else str(asset.get("browser_download_url") or "")
        if not url:
            continue
        apks.append(
            ReleaseApk(
                abi=abi,
                file_name=name,
                url=url,
                sha256=sha256,
                size_bytes=int(asset.get("size") or 0),
            )
        )
    if not apks:
        return None
    return AppRelease(
        version_name=tag.removeprefix("v"),
        notes=str(payload.get("body") or ""),
        published_at=payload.get("published_at"),
        apks=tuple(sorted(apks, key=lambda apk: apk.abi)),
    )


class GithubReleaseSource:
    def __init__(
        self,
        *,
        repo: str,
        cache: StringCache,
        cache_seconds: int,
        mirror_base_url: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._repo = repo.strip().strip("/")
        self._cache = cache
        self._cache_seconds = cache_seconds
        self._mirror = mirror_base_url
        self._transport = transport

    async def latest(self) -> AppRelease | None:
        if not self._repo:
            return None
        cached = await self._cache.get(CACHE_KEY)
        if cached is not None:
            return None if cached == _NO_RELEASE else _decode(cached)

        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{self._repo}/releases/latest",
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "geekvpn-api"},
                )
        except httpx.HTTPError:
            logger.warning("app_release.github_unreachable", extra={"repo": self._repo})
            return None

        if response.status_code == httpx.codes.NOT_FOUND:
            # No release published yet: a normal state, worth remembering.
            await self._cache.set(CACHE_KEY, _NO_RELEASE, ttl_seconds=self._cache_seconds)
            return None
        if response.status_code != httpx.codes.OK:
            logger.warning(
                "app_release.github_refused",
                extra={"repo": self._repo, "status": response.status_code},
            )
            return None

        try:
            release = parse_release(response.json(), mirror_base_url=self._mirror)
        except (ValueError, TypeError, AttributeError):
            logger.warning("app_release.unreadable", extra={"repo": self._repo})
            return None
        await self._cache.set(
            CACHE_KEY,
            _NO_RELEASE if release is None else json.dumps(asdict(release)),
            ttl_seconds=self._cache_seconds,
        )
        return release


def _decode(raw: str) -> AppRelease | None:
    try:
        data = json.loads(raw)
        return AppRelease(
            version_name=data["version_name"],
            notes=data["notes"],
            published_at=data["published_at"],
            apks=tuple(ReleaseApk(**apk) for apk in data["apks"]),
        )
    except (ValueError, KeyError, TypeError):
        return None
