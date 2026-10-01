"""What the Android app asks at start: is there a newer version of me?

Public, like the sign-in routes beside it: a signed-out app must still be able
to update, and nothing here is about the customer. See
`infrastructure/app_release.py` for where the answer comes from.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from geekvpn.application.platform.settings_service import (
    APP_PROMO_BODY_FA,
    APP_PROMO_COUPON,
    APP_PROMO_TITLE_FA,
    APP_PROMO_UNTIL,
)
from geekvpn.application.provisioning.usage_history import tehran_day
from geekvpn.infrastructure.app_release import AppRelease, GithubReleaseSource
from geekvpn.infrastructure.desktop_release import DesktopReleaseSource, update_for
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import ScopeDep

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


@router.get(
    "/desktop/update/{target}/{arch}/{current_version}",
    summary="The desktop app's update, in Tauri's updater format",
    responses={
        status.HTTP_200_OK: {"description": "A newer version for this platform"},
        status.HTTP_204_NO_CONTENT: {"description": "Nothing newer"},
    },
)
async def desktop_update(
    target: str, arch: str, current_version: str, container: ContainerDep, bundle: str = ""
) -> Response:
    """What the desktop app's built-in updater asks, with its own variables.

    Public like `/version`. 204 is the updater's "nothing newer", including
    when updates are off or GitHub cannot be reached: the app simply asks
    again later, and falls back to GitHub itself if it can reach it.
    """
    settings = container.settings.app_release
    source = DesktopReleaseSource(
        repo=settings.desktop_github_repo,
        cache=container.cache,
        cache_seconds=settings.cache_seconds,
        mirror_base_url=settings.mirror_base_url,
    )
    answer = update_for(
        await source.latest(),
        target=target,
        arch=arch,
        bundle=bundle,
        current_version=current_version,
        min_version=settings.desktop_min_version,
    )
    if answer is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Tauri's own field names (`pub_date`), not the camelCase of the rest.
    return JSONResponse(answer)


class AppPromo(ApiModel):
    title_fa: str
    body_fa: str
    #: Filled in at checkout; the quote decides whether it applies.
    coupon_code: str | None
    #: Last day shown (Tehran), ISO; None = until the operator removes it.
    until: str | None


class AppPromoResponse(ApiModel):
    #: None when there is no offer running.
    promo: AppPromo | None


def current_promo(
    *, title: str, body: str, coupon: str, until: str, today: date
) -> AppPromo | None:
    """The banner the settings describe, if one is running today. Pure."""
    if not title.strip():
        return None
    last_day: date | None = None
    if until.strip():
        try:
            last_day = date.fromisoformat(until.strip())
        except ValueError:
            # A typo in the date must not show an offer forever.
            return None
        if today > last_day:
            return None
    return AppPromo(
        title_fa=title.strip(),
        body_fa=body.strip(),
        coupon_code=coupon.strip() or None,
        until=last_day.isoformat() if last_day else None,
    )


@router.get("/promo", response_model=AppPromoResponse, summary="The offer banner, if any")
async def promo(scope: ScopeDep) -> AppPromoResponse:
    """Public, like `/version`: a guest sees the offer too, and signs in to use it.

    Set from the admin panel's settings (``app.promo_*``), so an offer starts
    and ends without an app release.
    """
    settings = scope.settings_service
    return AppPromoResponse(
        promo=current_promo(
            title=await settings.get(APP_PROMO_TITLE_FA),
            body=await settings.get(APP_PROMO_BODY_FA),
            coupon=await settings.get(APP_PROMO_COUPON),
            until=await settings.get(APP_PROMO_UNTIL),
            today=tehran_day(scope.container.clock.now()),
        )
    )
