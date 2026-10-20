"""The desktop app's latest release, for its built-in updater.

The desktop app's release workflow attaches `latest.json` to every GitHub
release: Tauri's update manifest, one entry per platform (`windows-x86_64`,
`darwin-aarch64-app`, `linux-x86_64-deb`, ...) with the package's URL and its
minisign signature. This reads that manifest and answers the updater's
"is there something newer than mine?" with the one entry for the asking
platform, in Tauri's dynamic-server shape.

The package URLs are pointed at the mirror when there is one, as for the
Android APKs. Unlike them, nothing here has to be trusted: the app checks
each package's signature against the key built into it, and the version the
signature was made for, so neither a mirror nor this API can swap a package
or roll an app back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from geekvpn.infrastructure.app_release import StringCache
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 10.0
CACHE_KEY = "desktop_release:latest"
MANIFEST_NAME = "latest.json"
_NO_RELEASE = "none"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")
#: What the updater may put in `{{target}}`, `{{arch}}` and `{{bundle_type}}`.
_TOKEN = re.compile(r"^[a-z0-9_]{1,16}$")


@dataclass(frozen=True, slots=True)
class DesktopPackage:
    url: str
    signature: str


@dataclass(frozen=True, slots=True)
class DesktopRelease:
    version: str
    notes: str
    pub_date: str | None
    #: `windows-x86_64`, `windows-x86_64-nsis`, `darwin-aarch64-app`, ...
    platforms: dict[str, DesktopPackage] = field(default_factory=dict)


def version_tuple(version: str) -> tuple[int, int, int] | None:
    """`1.2.0`, `v1.2.0` or `1.2.0-beta.1` as a comparable triple; None if not a version."""
    match = _VERSION.match(version.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def parse_manifest(
    payload: Mapping[str, Any], *, mirror_base_url: str = ""
) -> DesktopRelease | None:
    """A `latest.json` as a `DesktopRelease`, or None if it describes nothing installable."""
    version = str(payload.get("version") or "").strip().removeprefix("v")
    if version_tuple(version) is None:
        return None
    mirror = mirror_base_url.strip().rstrip("/")
    platforms: dict[str, DesktopPackage] = {}
    raw_platforms = payload.get("platforms")
    if not isinstance(raw_platforms, Mapping):
        return None
    for key, entry in raw_platforms.items():
        if not isinstance(entry, Mapping):
            continue
        url = str(entry.get("url") or "")
        signature = str(entry.get("signature") or "")
        if not url.startswith("https://") or not signature:
            continue
        if mirror:
            url = f"{mirror}/{urlsplit(url).path.rsplit('/', 1)[-1]}"
        platforms[str(key)] = DesktopPackage(url=url, signature=signature)
    if not platforms:
        return None
    return DesktopRelease(
        version=version,
        notes=str(payload.get("notes") or ""),
        pub_date=payload.get("pub_date"),
        platforms=platforms,
    )


def update_for(
    release: DesktopRelease | None,
    *,
    target: str,
    arch: str,
    bundle: str,
    current_version: str,
    min_version: str,
) -> dict[str, Any] | None:
    """The updater's answer for one installed app, or None for "nothing newer".

    The updater looks up `{target}-{arch}-{bundle}` before `{target}-{arch}`,
    and so does this: an NSIS install must not be handed an MSI.
    """
    if release is None:
        return None
    current = version_tuple(current_version)
    latest = version_tuple(release.version)
    if current is None or latest is None or latest <= current:
        return None
    if not (_TOKEN.match(target) and _TOKEN.match(arch)):
        return None
    keys = [f"{target}-{arch}-{bundle}"] if bundle and _TOKEN.match(bundle) else []
    keys.append(f"{target}-{arch}")
    package = next((release.platforms[k] for k in keys if k in release.platforms), None)
    if package is None:
        return None
    floor = version_tuple(min_version) if min_version.strip() else None
    return {
        "version": release.version,
        "notes": release.notes,
        "pub_date": release.pub_date,
        "url": package.url,
        "signature": package.signature,
        "required": floor is not None and current < floor,
    }


class DesktopReleaseSource:
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

    async def latest(self) -> DesktopRelease | None:
        if not self._repo:
            return None
        cached = await self._cache.get(CACHE_KEY)
        if cached is not None:
            return None if cached == _NO_RELEASE else _decode(cached)

        headers = {"Accept": "application/vnd.github+json", "User-Agent": "geekvpn-api"}
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, transport=self._transport, follow_redirects=True
            ) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{self._repo}/releases/latest", headers=headers
                )
                if response.status_code == httpx.codes.NOT_FOUND:
                    await self._remember(None)
                    return None
                if response.status_code != httpx.codes.OK:
                    logger.warning(
                        "desktop_release.github_refused",
                        extra={"repo": self._repo, "status": response.status_code},
                    )
                    return None
                manifest_url = next(
                    (
                        str(asset.get("browser_download_url") or "")
                        for asset in response.json().get("assets") or ()
                        if asset.get("name") == MANIFEST_NAME
                    ),
                    "",
                )
                if not manifest_url:
                    # A release without the manifest (a build without the
                    # signing key) has nothing the updater could verify.
                    await self._remember(None)
                    return None
                manifest = await client.get(manifest_url, headers={"User-Agent": "geekvpn-api"})
        except httpx.HTTPError:
            logger.warning("desktop_release.github_unreachable", extra={"repo": self._repo})
            return None
        except (ValueError, AttributeError):
            logger.warning("desktop_release.unreadable", extra={"repo": self._repo})
            return None

        if manifest.status_code != httpx.codes.OK:
            logger.warning(
                "desktop_release.manifest_refused",
                extra={"repo": self._repo, "status": manifest.status_code},
            )
            return None
        try:
            release = parse_manifest(manifest.json(), mirror_base_url=self._mirror)
        except (ValueError, TypeError, AttributeError):
            logger.warning("desktop_release.manifest_unreadable", extra={"repo": self._repo})
            return None
        await self._remember(release)
        return release

    async def _remember(self, release: DesktopRelease | None) -> None:
        await self._cache.set(
            CACHE_KEY,
            _NO_RELEASE if release is None else json.dumps(asdict(release)),
            ttl_seconds=self._cache_seconds,
        )


def _decode(raw: str) -> DesktopRelease | None:
    try:
        data = json.loads(raw)
        return DesktopRelease(
            version=data["version"],
            notes=data["notes"],
            pub_date=data["pub_date"],
            platforms={key: DesktopPackage(**entry) for key, entry in data["platforms"].items()},
        )
    except (ValueError, KeyError, TypeError):
        return None
