"""Async engine and session factory."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from geekvpn.infrastructure.config.settings import PostgresSettings


def create_engine(settings: PostgresSettings) -> AsyncEngine:
    return create_async_engine(
        settings.dsn(),
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        # Detects connections killed by a restart or a failover before use.
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def create_reporting_engine(settings: PostgresSettings) -> Engine:
    """Synchronous engine used only by analytics.

    Analytics readers are synchronous by design: they run one aggregate query
    each, from the admin panel or an export, never from the customer hot path.
    Giving them their own small pool means a slow report cannot exhaust the
    async pool that the bot and the Mini App share.
    """
    return _create_sync_engine(
        settings.dsn(driver="psycopg") if _accepts_driver(settings) else settings.dsn(),
        echo=settings.echo,
        # Deliberately small. Reports are rare and expensive; queueing behind a
        # couple of connections is better than starving the write path.
        pool_size=2,
        max_overflow=2,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
    )


def _accepts_driver(settings: PostgresSettings) -> bool:
    """True when ``dsn()`` can build a synchronous URL for us."""
    try:
        settings.dsn(driver="psycopg")
    except TypeError:
        return False
    return True


def create_write_sync_engine(settings: PostgresSettings) -> Engine:
    """Synchronous engine for the *write* path of synchronous services.

    Deliberately not the reporting engine. Reporting has a pool of two on
    purpose, so a slow report cannot starve anything else; sharing it would
    mean an operator approving a payment queues behind an export of the annual
    revenue report. Two pools with two jobs, each sized for its job.
    """
    return _create_sync_engine(
        settings.dsn(driver="psycopg") if _accepts_driver(settings) else settings.dsn(),
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
    )


def create_sync_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
