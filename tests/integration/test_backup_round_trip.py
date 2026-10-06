"""A backup is only as good as its restore.

Written against a database migrated the real way, because the restore checks
the schema revision and a `create_all` database has none.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from geekvpn.infrastructure.backup.archive import (
    BackupError,
    export_archive,
    read_manifest,
    restore_archive,
)
from geekvpn.infrastructure.config.settings import get_settings

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def dsn() -> str:
    return get_settings().postgres.dsn(driver="postgresql+psycopg")


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(dsn(), pool_pre_ping=True)
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", dsn())
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


def seed(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO platform_settings (key, value, is_secret) VALUES "
                "('support.hours', '\"line one\\nline two, with a comma\"', false)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO funnel_events (user_id, stage, occurred_at) "
                "VALUES (1, 'storefront', now()), (2, 'storefront', now())"
            )
        )


def test_what_was_backed_up_is_what_comes_back(engine: Engine, tmp_path: Path) -> None:
    seed(engine)
    archive = tmp_path / "backup.zip"

    summary = export_archive(engine, archive, created_at=NOW)

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM platform_settings"))
        connection.execute(text("INSERT INTO funnel_events (user_id, stage, occurred_at) VALUES (9, 'storefront', now())"))

    loaded = restore_archive(engine, archive)

    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT value FROM platform_settings WHERE key = 'support.hours'")
        ).scalar_one()
        users = connection.execute(text("SELECT user_id FROM funnel_events ORDER BY id")).scalars().all()
    assert value == "line one\nline two, with a comma"
    assert users == [1, 2]
    assert loaded["funnel_events"] == 2
    assert summary.rows["funnel_events"] == 2


def test_a_restored_serial_column_does_not_collide_on_the_next_insert(
    engine: Engine, tmp_path: Path
) -> None:
    seed(engine)
    archive = tmp_path / "backup.zip"
    export_archive(engine, archive, created_at=NOW)

    restore_archive(engine, archive)

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO funnel_events (user_id, stage, occurred_at) VALUES (3, 'storefront', now())")
        )
        count = connection.execute(text("SELECT count(*) FROM funnel_events")).scalar_one()
    assert count == 3


def test_the_manifest_names_the_schema_it_came_from(engine: Engine, tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    export_archive(engine, archive, created_at=NOW)

    manifest = read_manifest(archive)

    with engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert manifest["revision"] == current
    assert manifest["created_at"] == NOW.isoformat()


def test_a_backup_from_another_schema_revision_is_refused(engine: Engine, tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    export_archive(engine, archive, created_at=NOW)
    forged = tmp_path / "old.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(forged, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.json":
                data = data.replace(b'"revision": "', b'"revision": "0001_')
            target.writestr(name, data)

    with pytest.raises(BackupError):
        restore_archive(engine, forged)
