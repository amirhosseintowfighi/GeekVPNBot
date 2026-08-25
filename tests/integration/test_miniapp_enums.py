"""The Mini App's string unions must list every value the API can send.

A missing member is not a type error anywhere - it is a lookup that returns
`undefined` at runtime, and the line after it reads a property off that. The
support page died with "a client-side exception has occurred" the moment any
ticket was answered, because `waiting` was missing from `TicketState` and from
the map keyed by it.

The same shape has now appeared three times: `revoked` missing from the admin's
subscription states, `waiting` here, and the storefront's field names before
them. Two languages describing one contract, with nothing comparing them.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import pytest

from geekvpn.application.bot import read_models

pytestmark = pytest.mark.integration

TYPES = Path(__file__).resolve().parents[2] / "miniapp" / "src" / "lib" / "types.ts"

#: TypeScript union -> the Python enum the API serialises into it.
UNIONS: dict[str, type[Enum]] = {
    "SubscriptionState": read_models.SubscriptionState,
    "TransactionKind": read_models.TransactionKind,
    "PaymentMethod": read_models.PaymentMethod,
    "ServerHealth": read_models.ServerHealth,
    "TicketState": read_models.TicketState,
}


def _members(union: str) -> set[str]:
    source = TYPES.read_text(encoding="utf-8")
    match = re.search(rf"export type {union} =\s*((?:\s*\|?\s*'[^']*')+)", source)
    assert match, f"{union} is gone from the Mini App's types"
    return set(re.findall(r"'([^']*)'", match.group(1)))


@pytest.mark.parametrize(("union", "enum"), UNIONS.items())
def test_the_union_lists_every_value_the_api_can_send(union: str, enum: type[Enum]) -> None:
    missing = {member.value for member in enum} - _members(union)

    assert not missing, (
        f"{union} does not list {sorted(missing)}, so a payload carrying one "
        "looks up undefined and whatever reads the next property throws"
    )
