"""Analytics endpoints for the admin panel.

One round trip per screen, on purpose. Six independent requests would let the
metric cards and the charts describe different periods while they load, and a
revenue figure that disagrees with the chart beneath it destroys trust in the
whole report.

The readers are synchronous by design (see ``application/analytics/ports.py``),
so every handler hands the work to a worker thread. Running a multi-second
aggregate on the event loop would stall the bot and the Mini App, which share
the same process.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from starlette.concurrency import run_in_threadpool

from geekvpn.application.analytics.analytics_service import DEFAULT_DAYS, AnalyticsService
from geekvpn.application.analytics.dashboard_service import DashboardService
from geekvpn.application.analytics.export import CONTENT_TYPE, bundle_csv, filename_for
from geekvpn.application.analytics.gamification_service import GamificationService
from geekvpn.application.analytics.marketing import MarketingService
from geekvpn.application.analytics.segmentation_service import SegmentationService
from geekvpn.domain.analytics.enums import SegmentKind
from geekvpn.domain.identity.permissions import Permission
from geekvpn.infrastructure.analytics.sql_readers import build_readers
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import CurrentAdmin, requires

router = APIRouter(prefix="/admin/analytics", tags=["analytics"])

#: A bounded window. An unbounded ``days`` would let a mistyped URL start a
#: multi-year unindexed scan.
DaysQuery = Annotated[
    int,
    Query(ge=1, le=365, description="Reporting window in days: 7, 30, 90 or 365."),
]


def _services(container: ContainerDep) -> dict[str, Any]:
    """Build the analytics graph around one synchronous reporting session."""
    session = container.reporting_sessions()
    readers = build_readers(session)
    clock = container.clock
    segmentation = SegmentationService(customers=readers.customers, clock=clock)
    return {
        "session": session,
        "analytics": AnalyticsService(readers=readers, clock=clock),
        "dashboard": DashboardService(readers=readers, clock=clock),
        "segmentation": segmentation,
        "marketing": MarketingService(readers=readers, segmentation=segmentation, clock=clock),
        "gamification": GamificationService(readers=readers, clock=clock),
    }


async def _run(container: ContainerDep, work: Callable[[Any], Any]) -> Any:
    """Run one synchronous report off the event loop and always close its session."""
    services = _services(container)

    def _call() -> Any:
        try:
            return work(services)
        finally:
            services["session"].close()

    return await run_in_threadpool(_call)


@router.get(
    "",
    summary="The whole analytics bundle for one period",
    dependencies=[Depends(requires(Permission.ANALYTICS_VIEW))],
)
async def bundle(
    container: ContainerDep,
    admin: CurrentAdmin,
    days: DaysQuery = DEFAULT_DAYS,
) -> dict[str, Any]:
    return await _run(container, lambda s: s["analytics"].bundle(days=days).as_dict())


@router.get(
    "/export",
    summary="The same bundle as a CSV",
    dependencies=[Depends(requires(Permission.ANALYTICS_EXPORT))],
    response_class=Response,
)
async def export(
    container: ContainerDep,
    admin: CurrentAdmin,
    days: DaysQuery = DEFAULT_DAYS,
) -> Response:
    body = await _run(container, lambda s: bundle_csv(s["analytics"].bundle(days=days)))
    return Response(
        content=body,
        media_type=CONTENT_TYPE,
        headers={
            # An ASCII filename on purpose: a Persian name in
            # Content-Disposition needs RFC 5987 and still breaks older
            # clients. The Persian lives inside the file, where Excel reads it.
            "Content-Disposition": f'attachment; filename="{filename_for(days)}"',
        },
    )


@router.get(
    "/dashboard",
    summary="The operator work queue",
    dependencies=[Depends(requires(Permission.ANALYTICS_VIEW))],
)
async def dashboard(container: ContainerDep, admin: CurrentAdmin) -> dict[str, Any]:
    return await _run(container, lambda s: s["dashboard"].build().as_dict())


@router.get(
    "/marketing",
    summary="Suggested campaigns and under-performing ones",
    dependencies=[Depends(requires(Permission.ANALYTICS_VIEW))],
)
async def marketing(
    container: ContainerDep,
    admin: CurrentAdmin,
    days: DaysQuery = DEFAULT_DAYS,
) -> dict[str, Any]:
    def work(s: dict[str, Any]) -> dict[str, Any]:
        service = s["marketing"]
        return {
            "suggestions": [item.as_dict() for item in service.suggestions(days=days)],
            "ranking": [item.as_dict() for item in service.campaign_ranking(days=days)],
            "underperformers": [item.as_dict() for item in service.underperformers(days=days)],
        }

    return await _run(container, work)


@router.get(
    "/leaderboard",
    summary="Referral leaderboard",
    dependencies=[Depends(requires(Permission.ANALYTICS_VIEW))],
)
async def leaderboard(
    container: ContainerDep,
    admin: CurrentAdmin,
    days: DaysQuery = DEFAULT_DAYS,
) -> dict[str, Any]:
    def work(s: dict[str, Any]) -> dict[str, Any]:
        return {"rows": [row.as_dict() for row in s["gamification"].leaderboard(days=days)]}

    return await _run(container, work)


@router.get(
    "/segments/{kind}",
    summary="Resolve one customer segment to an audience",
    dependencies=[Depends(requires(Permission.ANALYTICS_VIEW))],
)
async def segment_audience(
    kind: SegmentKind,
    container: ContainerDep,
    admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=50_000)] = 1_000,
) -> dict[str, Any]:
    def work(s: dict[str, Any]) -> dict[str, Any]:
        audience = s["segmentation"].audience(kind, limit=limit)
        return {
            "kind": audience.kind.value,
            "labelFa": audience.label_fa,
            "size": audience.size,
            "userIds": list(audience.user_ids),
        }

    return await _run(container, work)


__all__ = ["router"]
