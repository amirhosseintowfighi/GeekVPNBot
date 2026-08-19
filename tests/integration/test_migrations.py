"""The schema must actually build, and must match the models.

`alembic upgrade head` had never once been run against an empty database.
Everything green said the code was right; nothing said the schema could be
created at all. It could not - twice over:

* two revision ids were longer than the ``VARCHAR(32)`` Alembic hardcodes for
  ``alembic_version.version_num``, so stamping them failed;
* 0004 recreated three indexes 0003 had already made, so the upgrade raised
  DuplicateTable even once stamping worked.

Both were invisible to every other test in this suite, because none of them
touch Postgres. Most of this file needs a real database and skips without one,
so it runs in CI and on a server and stays honest about being unproven
elsewhere - which is exactly why the revision-id check below is written to need
no database at all. The first attempt at that check asserted the presence of a
string in env.py rather than the property it stood for, passed, and let the
same failure reach a real server a second time.
"""

from __future__ import annotations

import re

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

#: Longest revision id in the tree. Alembic creates the column as VARCHAR(32)
#: and provides no way to widen it, so this must stay under that.
LONGEST_REVISION = "0003_billing_and_support"


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


def revision_ids() -> dict[str, str]:
    """Every id declared in the tree, mapped to the file that declares it."""
    from pathlib import Path

    found: dict[str, str] = {}
    pattern = re.compile(r"^(?:revision|down_revision)[^=]*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
    for path in sorted(Path("migrations/versions").glob("*.py")):
        for identifier in pattern.findall(path.read_text(encoding="utf-8")):
            found.setdefault(identifier, path.name)
    return found


def test_no_revision_id_exceeds_the_column_alembic_actually_creates() -> None:
    """The replacement for a test that checked the wrong thing.

    The previous fix passed `version_table_column_length=64` to
    `context.configure`, and a test asserted that string appeared twice in
    env.py. No such option exists: Alembic hardcodes String(32) in
    `DefaultImpl.version_table_impl`, and `configure` takes **kw and drops
    what it does not recognise. So the setting did nothing, the test passed,
    and `upgrade head` still died at 0003 on a real server.

    This asserts the limit against Alembic's own table definition instead of
    against the text of our source, and needs no database - which matters,
    because everything else in this file skips without one.
    """
    from alembic.ddl.impl import DefaultImpl

    column = DefaultImpl.version_table_impl(
        DefaultImpl,  # type: ignore[arg-type]
        version_table="alembic_version",
        version_table_schema=None,
        version_table_pk=True,
    ).c.version_num
    limit = column.type.length
    assert limit, "Alembic's version column is no longer length-bound; this test can go"

    too_long = {
        identifier: source
        for identifier, source in revision_ids().items()
        if len(identifier) > limit
    }
    assert not too_long, (
        f"Alembic creates alembic_version.version_num as VARCHAR({limit}) and cannot be "
        "told otherwise, so stamping these fails on a fresh database:\n  "
        + "\n  ".join(
            f"{name} ({len(name)} chars, in {source})" for name, source in too_long.items()
        )
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
