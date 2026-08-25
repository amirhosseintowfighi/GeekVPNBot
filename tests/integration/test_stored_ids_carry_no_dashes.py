"""A parsed UUID must be converted before it is used as a stored id.

Ids are stored as `uuid4().hex` - thirty-two characters, no dashes. A
`uuid.UUID` renders with them, so handing one to a repository looks up a row
that cannot exist. Nothing raises: the lookup simply finds nothing, and what
the customer sees is "something went wrong".

This has now been fixed three times in three places - the payment id in the
Mini App's payment screen, the ticket id in the bot, and the ticket id in the
Mini App - so it is checked rather than remembered.

The rule: a function that takes a `uuid.UUID` may not pass that name straight
into a scope call. `.hex` is the conversion, and it belongs in one place per
function rather than at each use.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2] / "src" / "geekvpn"

#: Where a stored id is handed to something that will query on it.
SCOPES = {"scope", "sync", "self._session"}

#: Only the tables whose primary key is a `String(64)` holding `uuid4().hex`.
#:
#: The catalogue is deliberately not here: categories, products, plans and
#: coupons are stored in real `UUID` columns, so a `uuid.UUID` is exactly what
#: those queries want and converting one would break them. Two conventions in
#: one schema is itself worth knowing about, and this list is where that fact
#: is written down.
HEX_STORED = {"ticket_id", "payment_id", "subscription_id", "order_id", "message_id"}


def _uuid_parameters(function: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    named: set[str] = set()
    arguments = function.args
    for argument in [*arguments.args, *arguments.kwonlyargs, *arguments.posonlyargs]:
        annotation = argument.annotation
        if annotation is None:
            continue
        text = ast.unparse(annotation)
        if text in {"uuid.UUID", "UUID"}:
            named.add(argument.arg)
    return named


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []

    for function in ast.walk(tree):
        if not isinstance(function, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        parsed = _uuid_parameters(function)
        if not parsed:
            continue

        for call in ast.walk(function):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            target = ast.unparse(call.func)
            if not any(target.startswith(f"{scope}.") for scope in SCOPES):
                continue
            for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
                if (
                    isinstance(argument, ast.Name)
                    and argument.id in parsed
                    and argument.id in HEX_STORED
                ):
                    found.append(f"{path.name}:{function.name} passes {argument.id} to {target}")
    return found


def test_the_rule_is_applied_somewhere() -> None:
    """A guard against the walk silently matching nothing."""
    routers = ROOT / "presentation" / "api" / "routers"
    assert any("uuid.UUID" in file.read_text(encoding="utf-8") for file in routers.glob("*.py"))


def test_no_parsed_uuid_is_used_as_a_stored_id() -> None:
    offences: list[str] = []
    for file in ROOT.rglob("*.py"):
        offences.extend(_offences(file))

    assert not offences, (
        "a `uuid.UUID` reaches a repository with its dashes, which finds no row "
        "and reports nothing:\n  " + "\n  ".join(offences)
    )
