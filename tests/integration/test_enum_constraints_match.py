"""An enum in Python and a list of strings frozen in a migration.

`admins.role` carries a check constraint listing the roles that existed when
the table was created. Adding `RESELLER` to `AdminRole` updated the model's
constraint - which nothing applies to a live database - and left the deployed
one alone. Every attempt to create a reseller then failed on an insert the API
could only report as "something went wrong", and no test noticed, because the
model and the migration were each internally consistent.

This compares them. The model's constraints are generated from the enums, so
they are the truth; the migrations are what a real database actually has.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from geekvpn.infrastructure.persistence import models  # noqa: F401
from geekvpn.infrastructure.persistence.base import Base

pytestmark = pytest.mark.integration

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"

#: `column IN ('a', 'b')`, however it is spelled across the two sources.
_IN_CLAUSE = re.compile(r"(\w+)\s+IN\s+\(([^)]*)\)", re.IGNORECASE)


def _values(clause: str) -> frozenset[str]:
    return frozenset(re.findall(r"'([^']*)'", clause))


def _model_constraints() -> dict[tuple[str, str], frozenset[str]]:
    """Every `column IN (...)` the models declare, by table and column."""
    found: dict[tuple[str, str], frozenset[str]] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            text = str(getattr(constraint, "sqltext", ""))
            for column, listed in _IN_CLAUSE.findall(text):
                found[(table.name, column.lower())] = _values(listed)
    return found


def _migration_constraints() -> dict[tuple[str, str], frozenset[str]]:
    """The same, as the migrations leave them.

    Files are read in name order, and a later one wins: a migration that
    replaces a constraint is exactly how this drift gets fixed, and reading
    only the first would report every fix as a failure.
    """
    found: dict[tuple[str, str], frozenset[str]] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Only the upgrade half. A downgrade restores the old, narrower list on
        # purpose, and reading it would compare the model against history.
        upgrade = source.split("def downgrade")[0]
        table = None
        for line in upgrade.splitlines():
            named = re.search(r'(?:create_table|create_check_constraint\([^,]+,)\s*"(\w+)"', line)
            if named:
                table = named.group(1)
            for column, listed in _IN_CLAUSE.findall(line):
                if table:
                    found[(table, column.lower())] = _values(listed)
    return found


def test_every_enum_constraint_allows_what_the_enum_allows():
    """The model is the truth; the migration is what the database has."""
    models_say = _model_constraints()
    migrations_say = _migration_constraints()

    drifted = {
        key: (sorted(models_say[key] - migrations_say[key]), sorted(migrations_say[key] - models_say[key]))
        for key in models_say
        if key in migrations_say and models_say[key] != migrations_say[key]
    }

    assert not drifted, (
        "these columns accept different values in the model and in the database: "
        f"{drifted} - a value only the model knows about fails on insert"
    )


def test_the_comparison_actually_found_something():
    """A parser that quietly matches nothing would pass the test above
    forever, which is a worse outcome than the drift it is looking for."""
    models_say = _model_constraints()

    assert ("admins", "role") in models_say
    assert "reseller" in models_say[("admins", "role")]
    assert ("resellers", "status") in models_say
