"""Service metadata. Useful for smoke tests and deploy verification."""

from __future__ import annotations

from fastapi import APIRouter

from geekvpn import __version__
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.schemas import ServiceInfoResponse

router = APIRouter(tags=["meta"])


@router.get("/info", response_model=ServiceInfoResponse, summary="Service information")
async def info(container: ContainerDep) -> ServiceInfoResponse:
    settings = container.settings
    return ServiceInfoResponse(
        name=settings.app.name,
        version=__version__,
        environment=settings.app.env.value,
    )
