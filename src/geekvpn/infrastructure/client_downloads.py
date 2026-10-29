"""Where a customer downloads the Geek apps, read from their GitHub releases.

The same two sources the apps' own updaters read, so the bot, the Mini App
and the apps can never disagree about which version is current. Each answer
is the file itself when the release has one - the APK, the Windows installer -
and the repository's releases page when it does not, which still lands the
customer one tap from the download rather than on a dead button.

Mirror rewriting comes with the sources: when `mirror_base_url` is set, every
link here points at the copy reachable from Iran.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.infrastructure.app_release import (
    AppRelease,
    GithubReleaseSource,
    StringCache,
)
from geekvpn.infrastructure.config.settings import AppReleaseSettings
from geekvpn.infrastructure.desktop_release import DesktopRelease, DesktopReleaseSource

ANDROID = "android"
WINDOWS = "windows"

#: Most phones are arm64; the universal APK installs on all of them and is the
#: safe answer for a link that cannot ask which phone it is opened on.
_APK_PREFERENCE = ("universal", "arm64-v8a", "armeabi-v7a")
#: The updater's manifest keys for the Windows installer, NSIS first.
_WINDOWS_KEYS = ("windows-x86_64-nsis", "windows-x86_64", "windows-x86_64-msi")


@dataclass(frozen=True, slots=True)
class ClientDownload:
    #: `android` | `windows`
    platform: str
    #: None when only the releases page is known, not a published version.
    version: str | None
    url: str


def android_download(release: AppRelease | None, *, repo: str) -> ClientDownload | None:
    if release is not None:
        by_abi = {apk.abi: apk for apk in release.apks}
        for abi in _APK_PREFERENCE:
            if abi in by_abi:
                return ClientDownload(ANDROID, release.version_name, by_abi[abi].url)
    return _releases_page(ANDROID, repo)


def windows_download(release: DesktopRelease | None, *, repo: str) -> ClientDownload | None:
    if release is not None:
        for key in _WINDOWS_KEYS:
            package = release.platforms.get(key)
            if package is not None:
                return ClientDownload(WINDOWS, release.version, package.url)
    return _releases_page(WINDOWS, repo)


def _releases_page(platform: str, repo: str) -> ClientDownload | None:
    repo = repo.strip().strip("/")
    if not repo:
        return None
    return ClientDownload(platform, None, f"https://github.com/{repo}/releases/latest")


async def client_downloads(
    settings: AppReleaseSettings, cache: StringCache
) -> list[ClientDownload]:
    """Android first, then Windows; a platform with no repository is left out."""
    android = await GithubReleaseSource(
        repo=settings.github_repo,
        cache=cache,
        cache_seconds=settings.cache_seconds,
        mirror_base_url=settings.mirror_base_url,
    ).latest()
    windows = await DesktopReleaseSource(
        repo=settings.desktop_github_repo,
        cache=cache,
        cache_seconds=settings.cache_seconds,
        mirror_base_url=settings.mirror_base_url,
    ).latest()
    found = [
        android_download(android, repo=settings.github_repo),
        windows_download(windows, repo=settings.desktop_github_repo),
    ]
    return [download for download in found if download is not None]
