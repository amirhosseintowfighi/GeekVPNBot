"""The bot speaks UUIDs; the payment store speaks strings without dashes.

`Uuid4IdGenerator` returns `uuid4().hex` - thirty-two characters, no dashes -
and every payment id in the database is written that way. The bot layer hands
the handlers a `uuid.UUID`, and turning that back with `str()` puts the dashes
in: a payment created as "e89789f92d04…" was looked up as "e89789f9-2d04-…".

Nothing matched, so every card receipt a customer sent was answered with the
generic apology - after they had already transferred the money.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.infrastructure.bot.checkout import _as_stored_id, payment_uuid
from geekvpn.infrastructure.di.sync_scope import Uuid4IdGenerator

pytestmark = pytest.mark.unit


def test_an_id_survives_the_round_trip_the_receipt_flow_makes() -> None:
    stored = Uuid4IdGenerator().new_id()

    assert _as_stored_id(payment_uuid(stored)) == stored


def test_the_stored_form_carries_no_dashes() -> None:
    """The property the round trip broke, stated on its own."""
    stored = Uuid4IdGenerator().new_id()

    assert "-" not in stored
    assert len(stored) == 32


def test_str_would_not_have_worked() -> None:
    """Names the exact mistake, so a future edit cannot quietly reintroduce it."""
    stored = Uuid4IdGenerator().new_id()

    assert str(payment_uuid(stored)) != stored


def test_an_id_that_is_not_a_uuid_at_all_does_not_crash_the_handler() -> None:
    """A malformed id from an old message becomes the nil UUID, which finds no
    payment - a clean "not found" rather than a ValueError inside a handler."""
    assert payment_uuid("not-an-id") == uuid.UUID(int=0)
