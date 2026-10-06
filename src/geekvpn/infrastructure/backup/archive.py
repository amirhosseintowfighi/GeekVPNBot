"""A database backup that does not need `pg_dump`.

The runtime image has no PostgreSQL client, and the one Debian ships is older
than the server - a `pg_dump` older than its server refuses to run. So the
backup is the data itself: every table as CSV through `COPY`, in a zip, with a
manifest naming the schema revision it came from.

Restoring needs a database already migrated to that same revision (`alembic
upgrade head` on an empty one). The restore refuses any other revision rather
than guessing how columns moved, because a backup restored into the wrong
shape is worse than no restore at all.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import Engine, text

from geekvpn.infrastructure.persistence.base import Base

MANIFEST = "manifest.json"
FORMAT_VERSION = 1


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupSummary:
    path: Path
    revision: str
    rows: dict[str, int]
    size_bytes: int

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())


def _tables() -> list[str]:
    # Import every model module so the metadata is complete, then dependency
    # order: parents before children, which is also the order a restore
    # needs if foreign keys were ever checked.
    from geekvpn.infrastructure.persistence import models  # noqa: F401

    return [table.name for table in Base.metadata.sorted_tables]


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def export_archive(engine: Engine, destination: Path, *, created_at: datetime) -> BackupSummary:
    """Write every table to ``destination`` as a zip. Returns what went in.

    One repeatable-read transaction for all tables, so the backup is a single
    moment: an order and the payment that bought it are either both in or
    both out.
    """
    revision = _revision(engine)
    rows: dict[str, int] = {}
    raw = engine.raw_connection()
    connection = _psycopg(raw)
    try:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        with (
            connection.transaction(),
            connection.cursor() as cursor,
            zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive,
        ):
            for table in _tables():
                buffer = io.BytesIO()
                with cursor.copy(
                    f'COPY "{table}" TO STDOUT WITH (FORMAT csv, HEADER true)'
                ) as copy:
                    for chunk in copy:
                        buffer.write(bytes(chunk))
                payload = buffer.getvalue()
                rows[table] = _count(payload)
                archive.writestr(f"tables/{table}.csv", payload)
            archive.writestr(
                MANIFEST,
                json.dumps(
                    {
                        "format": FORMAT_VERSION,
                        "revision": revision,
                        "created_at": created_at.isoformat(),
                        "tables": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    finally:
        # Back to the pool's defaults before the connection is handed out again.
        connection.isolation_level = None
        connection.read_only = None
        raw.close()
    return BackupSummary(
        path=destination,
        revision=revision,
        rows=rows,
        size_bytes=destination.stat().st_size,
    )


def _psycopg(raw: object) -> psycopg.Connection[tuple[object, ...]]:
    connection = getattr(raw, "driver_connection", None)
    if not isinstance(connection, psycopg.Connection):
        raise BackupError("Backups need the psycopg driver.")
    # Whatever the pool left behind, a backup wants its own explicit
    # transaction rather than one opened implicitly by the first statement.
    connection.rollback()
    connection.autocommit = True
    return connection


def _count(payload: bytes) -> int:
    """Rows in a CSV with a header. Parsed, because a quoted field can hold a newline."""
    return max(0, sum(1 for _ in csv.reader(io.StringIO(payload.decode()))) - 1)


def read_manifest(source: Path) -> dict[str, object]:
    with zipfile.ZipFile(source) as archive:
        try:
            return dict(json.loads(archive.read(MANIFEST)))
        except KeyError as missing:
            raise BackupError("Not a GeekVPN backup: it has no manifest.") from missing


def restore_archive(engine: Engine, source: Path) -> dict[str, int]:
    """Replace every table's contents with the backup's. All or nothing.

    Triggers and foreign-key checks are suspended for the session
    (`session_replication_role = replica`) so tables can be loaded in any
    order, and the whole load is one transaction: a failure halfway leaves the
    database exactly as it was.
    """
    manifest = read_manifest(source)
    current = _revision(engine)
    if manifest.get("revision") != current:
        raise BackupError(
            f"The backup is from schema revision {manifest.get('revision')!r} and this "
            f"database is at {current!r}. Migrate an empty database to the backup's "
            "revision, restore, then upgrade."
        )

    tables = _tables()
    loaded: dict[str, int] = {}
    raw = engine.raw_connection()
    connection = _psycopg(raw)
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL session_replication_role = replica")
            cursor.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in tables)
                )
            )
            with zipfile.ZipFile(source) as archive:
                names = set(archive.namelist())
                for table in tables:
                    entry = f"tables/{table}.csv"
                    if entry not in names:
                        # A table added after the backup was taken: it stays empty.
                        continue
                    payload = archive.read(entry)
                    with cursor.copy(
                        sql.SQL("COPY {} FROM STDIN WITH (FORMAT csv, HEADER true)").format(
                            sql.Identifier(table)
                        )
                    ) as copy:
                        copy.write(payload)
                    loaded[table] = _count(payload)
            # Serial columns restart at 1 after the truncate; move each past the
            # highest id just loaded, or the next insert collides with a restored row.
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_default LIKE 'nextval(%'"
            )
            serials = [(str(table), str(column)) for table, column in cursor.fetchall()]
            for table, column in serials:
                cursor.execute(
                    sql.SQL(
                        "SELECT setval(pg_get_serial_sequence({qualified}, {column_name}),"
                        " COALESCE((SELECT MAX({column}) FROM {table}), 0) + 1, false)"
                    ).format(
                        qualified=sql.Literal(f'"{table}"'),
                        column_name=sql.Literal(column),
                        column=sql.Identifier(column),
                        table=sql.Identifier(table),
                    )
                )
    finally:
        raw.close()
    return loaded


__all__ = [
    "BackupError",
    "BackupSummary",
    "export_archive",
    "read_manifest",
    "restore_archive",
]
