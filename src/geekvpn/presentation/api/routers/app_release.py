"""What the Android app asks at start: is there a newer version of me?

Public, like the sign-in routes beside it: a signed-out app must still be able
to update, and nothing here is about the customer. See
`infrastructure/app_release.py` for where the answer comes from.
"""

from __future__ import annotations

from fastapi import APIRouter

from geekvpn.infrastructure.app_release import AppRelease, GithubReleaseSource
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep

router = APIRouter(prefix="/api/app", tags=["app"])


class AppApk(ApiModel):
    #: arm64-v8a | armeabi-v7a | x86 | x86_64 | universal
    abi: str
    file_name: str
    url: str
    sha256: str | None
    size_bytes: int


class AppLatest(ApiModel):
    version_name: str
    #: The release notes as published, Markdown.
    notes: str
    published_at: str | None
    apks: list[AppApk]


class AppVersionResponse(ApiModel):
    #: None while updates are switched off or nothing is published yet.
    latest: AppLatest | None
    #: Older versions must update; empty when none must.
    min_version: str


def _latest(release: AppRelease | None) -> AppLatest | None:
    if release is None:
        return None
    return AppLatest(
        version_name=release.version_name,
        notes=release.notes,
        published_at=release.published_at,
        apks=[
            AppApk(
                abi=apk.abi,
                file_name=apk.file_name,
                url=apk.url,
                sha256=apk.sha256,
                size_bytes=apk.size_bytes,
            )
            for apk in release.apks
        ],
    )


@router.get("/version", response_model=AppVersionResponse, summary="The app's latest release")
async def version(container: ContainerDep) -> AppVersionResponse:
    settings = container.settings.app_release
    source = GithubReleaseSource(
        repo=settings.github_repo,
        cache=container.cache,
        cache_seconds=settings.cache_seconds,
        mirror_base_url=settings.mirror_base_url,
    )
    return AppVersionResponse(
        latest=_latest(await source.latest()), min_version=settings.min_version.strip()
    )
