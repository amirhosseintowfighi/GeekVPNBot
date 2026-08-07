"""FastAPI dependency providers.

These are adapters between FastAPI's DI and our composition root. No business
logic lives here - they only resolve and scope objects.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.infrastructure.config.settings import Settings
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - only reachable on a broken lifespan
        raise RuntimeError("Dependency container is not initialised.")
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_settings_dep(container: ContainerDep) -> Settings:
    return container.settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


async def get_unit_of_work(container: ContainerDep) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """Request-scoped transaction. Rolls back automatically on error."""
    async with container.unit_of_work() as uow:
        yield uow


UnitOfWorkDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)]


async def get_session(uow: UnitOfWorkDep) -> AsyncSession:
    """Escape hatch for read-only endpoints that do not need a use case."""
    return uow.session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
