"""Health endpoints.

The distinction is deliberate and load-bearing:

* ``/health/live``  - is the process running? Never touches a dependency.
  If this fails, restart the container.
* ``/health/ready`` - can it serve traffic? Checks Postgres and Redis.
  If this fails, take it out of rotation but do NOT restart it: the process is
  fine, a dependency is not.

Conflating the two causes restart storms during a database blip.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from geekvpn import __version__
from geekvpn.infrastructure.health.probes import run_probes
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.schemas import (
    DependencyStatus,
    LivenessResponse,
    ReadinessResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
async def live(container: ContainerDep) -> LivenessResponse:
    return LivenessResponse(service=container.settings.app.name, version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"description": "One or more dependencies are unavailable"}},
)
async def ready(container: ContainerDep, response: Response) -> ReadinessResponse:
    results = await run_probes(container.health_probes)
    healthy = all(result.healthy for result in results)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if healthy else "degraded",
        dependencies=[
            DependencyStatus(
                name=result.name,
                healthy=result.healthy,
                latency_ms=result.latency_ms,
                error=result.error,
            )
            for result in results
        ],
    )
