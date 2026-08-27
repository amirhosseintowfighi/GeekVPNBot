"""A column the application never sends needs a default in the database.

`TimestampMixin` declares `created_at` and `updated_at` with a server default,
which means SQLAlchemy leaves them out of every INSERT and expects Postgres to
fill them in. A migration that creates those columns `NOT NULL` with no default
therefore rejects every insert into that table - not on some edge case, on the
first row.

Both reseller tables shipped that way. Creating a reseller failed in the panel
and submitting an application failed in the bot: one cause behind two doors,
and neither error could say anything more useful than "something went wrong".

The check is deliberately coarse. It asks whether the migration that creates a
timestamped table mentions a default for those columns *anywhere in the file* -
inline, through a shared `_TIMESTAMPS` tuple, or through a `_timestamps()`
helper, all three of which this project uses. Tying each column to its table
would mean following starred arguments and loop variables through the AST, and
a parser that elaborate is a second thing to get wrong. The coarse version
catches the mistake that actually happened and cannot be argued with.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from geekvpn.infrastructure.persistence import models  # noqa: F401
from geekvpn.infrastructure.persistence.base import Base

pytestmark = pytest.mark.integration

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"

TIMESTAMPS = ("created_at", "updated_at")


def _timestamped_tables() -> set[str]:
    """Tables whose timestamps the database is expected to fill in."""
    return {
        table.name
        for table in Base.metadata.tables.values()
        if all(
            column in table.columns
            and table.columns[column].server_default is not None
            and not table.columns[column].nullable
            for column in TIMESTAMPS
        )
    }


def _balanced(source: str, start: int) -> str:
    """From the opening bracket at or after `start` to its match."""
    depth = 0
    for index in range(source.index("(", start), len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return source[start:]


def _create_block(source: str, table: str) -> str | None:
    """The text of one `create_table(...)` call, brackets matched.

    Matched rather than split on lines: a table definition is fifty lines of
    nested calls, and nothing shorter reliably ends it.
    """
    found = re.search(rf'create_table\(\s*"{re.escape(table)}"', source)
    return _balanced(source, found.start()) if found else None


def _column_text(source: str, column: str) -> str | None:
    """One `Column("name", ...)`, brackets matched.

    Found by regex rather than by indentation: the same column is written at
    three different depths in this project - inline in a create_table, in a
    module-level tuple, and inside a helper function - and matching on leading
    spaces reads two of the three as absent.
    """
    found = re.search(rf'Column\(\s*"{re.escape(column)}"', source)
    return _balanced(source, found.start()) if found else None


def _defines_default(table: str, column: str) -> bool:
    """Does any migration give this column a default?

    Three places to look, because this project writes them three ways: inline
    in the create_table, in a shared definition the table splats, and in a
    later `alter_column` - which is how the bug this file exists for was fixed.
    """
    for path in sorted(MIGRATIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8").split("def downgrade")[0]

        block = _create_block(source, table)
        if block is not None:
            inline = _column_text(block, column)
            if inline is not None:
                if "server_default" in inline:
                    return True
            else:
                # Not written inline, so it comes from a shared group the file
                # also defines - `_TIMESTAMPS` or `_timestamps()`.
                shared = _column_text(source, column)
                if shared is not None and "server_default" in shared:
                    return True

        if (
            "alter_column" in source
            and "server_default" in source
            and f'"{table}"' in source
            and f'"{column}"' in source
        ):
            return True

    return False


def test_every_timestamped_table_has_a_default_for_its_timestamps():
    missing = sorted(
        f"{table}.{column}"
        for table in _timestamped_tables()
        for column in TIMESTAMPS
        if not _defines_default(table, column)
    )

    assert not missing, (
        "these columns are NOT NULL, the application never sends them, and the "
        f"database has no default - so every insert fails: {missing}"
    )


def test_the_check_reads_what_it_is_checking():
    """One that quietly matched nothing would pass forever - which is worse
    than the drift it is looking for."""
    tables = _timestamped_tables()

    assert "resellers" in tables
    assert "reseller_applications" in tables
    # Tables that were always correct, written all three ways: inline in
    # `users`, a shared tuple in the catalogue, a helper in billing. A checker
    # that reads none of them would fail here rather than pass forever.
    assert _defines_default("users", "created_at")
    assert _defines_default("catalog_plans", "created_at")
    assert _defines_default("billing_payments", "created_at")
