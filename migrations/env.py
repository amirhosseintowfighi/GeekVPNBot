"""Alembic environment.

Three things worth knowing:

1. The database URL comes from ``Settings``, never from ``alembic.ini``, so no
   credential is ever committed and migrations use the same configuration as
   the application.
2. Migrations take a Postgres advisory lock. The ``migrate`` service and every
   API replica can start simultaneously; only one will run the upgrade.
3. ``models`` is imported for its side effect: it registers every table on
   ``Base.metadata``. A model that is not reachable from that import is a model
   that autogenerate silently ignores.

On revision ids: Alembic hardcodes ``alembic_version.version_num`` as
``String(32)`` in ``DefaultImpl.version_table_impl`` and offers no option to
widen it - ``context.configure()`` takes ``**kw`` and silently ignores keys it
does not recognise, so a plausible-looking ``version_table_column_length=64``
sat here doing nothing while stamping kept failing. Ids are therefore kept
under 32 characters, which ``tests/integration/test_migrations.py`` asserts
without needing a database.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.persistence import models  # noqa: F401 - registers tables
from geekvpn.infrastructure.persistence.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.postgres.dsn())

target_metadata = Base.metadata

MIGRATION_LOCK_ID = 947_120_001


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        render_as_batch=False,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.postgres.dsn(driver="postgresql+psycopg"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID}
    )
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
