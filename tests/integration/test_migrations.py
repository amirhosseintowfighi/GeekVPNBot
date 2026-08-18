"""The schema must actually build, and must match the models.

`alembic upgrade head` had never once been run against an empty database.
Everything green said the code was right; nothing said the schema could be
created at all. It could not - twice over:

* two revision ids are longer than the ``VARCHAR(32)`` Alembic gives
  ``alembic_version.version_num`` by default, so stamping them failed;
* 0004 recreated three indexes 0003 had already made, so the upgrade raised
  DuplicateTable even once stamping worked.

Both were invisible to every other test in this suite, because none of them
touch Postgres. This one needs a real database and skips without one, so it
runs in CI and on a server and stays honest about being unproven elsewhere.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from geekvpn.infrastructure.config.settings import get_settings

# Imported for the side effect: a table is only on Base.metadata once its
# module has been imported, and compare_metadata against a half-populated
# metadata would report every missing table as a diff.
from geekvpn.infrastructure.persistence import models  # noqa: F401
from geekvpn.infrastructure.persistence.base import Base

pytestmark = pytest.mark.integration

#: Longest revision id in the tree. Alembic's default column is 32.
LONGEST_REVISION = "0003_billing_support_notifications_provisioning"


def sync_dsn() -> str:
    return get_settings().postgres.dsn(driver="postgresql+psycopg")


@pytest.fixture(scope="module")
def empty_database():
    """A connection to a database with the public schema dropped and recreated.

    Destructive by design and pointed only at the configured test database; a
    migration test that runs against a populated schema proves nothing about a
    fresh install, which is the case that was broken.
    """
    engine = create_engine(sync_dsn(), pool_pre_ping=True)
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        # Skipping is honest here: without a database this proves nothing, and
        # the whole point of the test is that it had never been run.
        pytest.skip(f"no Postgres available: {exc.__class__.__name__}")

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


def run_upgrade(engine) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_dsn())
    command.upgrade(config, "head")


def test_the_longest_revision_id_would_not_fit_the_default_column() -> None:
    """Guards the reason for the fix, without needing a database.

    If someone shortens the ids later this becomes noise and can go; while the
    long ones exist, `version_table_column_length` must stay set.
    """
    from pathlib import Path

    env = Path("migrations/env.py").read_text(encoding="utf-8")

    assert len(LONGEST_REVISION) > 32
    assert env.count("version_table_column_length=64") == 2, (
        "both the online and offline configure calls need it: offline writes "
        "the CREATE TABLE, online inserts into it"
    )


def test_upgrade_head_succeeds_on_an_empty_database(empty_database) -> None:
    run_upgrade(empty_database)

    tables = set(inspect(empty_database).get_table_names())
    assert "alembic_version" in tables
    # 30 model tables plus Alembic's own bookkeeping.
    assert len(tables - {"alembic_version"}) == 30


def test_the_version_column_is_wide_enough_for_every_revision(empty_database) -> None:
    run_upgrade(empty_database)

    with empty_database.connect() as connection:
        width = connection.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
            )
        ).scalar_one()
        stamped = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert width >= len(LONGEST_REVISION)
    assert stamped, "nothing was stamped, so the upgrade did not complete"


def test_the_schema_matches_the_models(empty_database) -> None:
    """The whole schema-drift class, pinned by one assertion.

    `compare_metadata` is what `alembic revision --autogenerate` uses, so an
    empty diff means a developer running it right now would get an empty
    migration - which is the only durable definition of "the models and the
    migrations agree".
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    run_upgrade(empty_database)

    with empty_database.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        diff = compare_metadata(context, Base.metadata)

    assert not diff, "\n".join(str(entry) for entry in diff)


def test_downgrade_one_and_upgrade_again(empty_database) -> None:
    """Every migration must be reversible; CLAUDE.md requires it and a deploy
    that cannot roll back is a deploy nobody dares make."""
    from alembic import command
    from alembic.config import Config

    run_upgrade(empty_database)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sync_dsn())

    command.downgrade(config, "-1")
    command.upgrade(config, "head")

    assert "alembic_version" in set(inspect(empty_database).get_table_names())
