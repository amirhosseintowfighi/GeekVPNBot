"""Two endpoints must spell a payment id the same way.

The Mini App starts a card payment, navigates to `/payments/<id>` with the id
that call returned, and then finds that payment in the list from
`/payments/pending`. If the two endpoints disagree about the spelling, the
lookup fails and the screen renders a skeleton forever - no error, no message,
nothing to report but "it hangs".

Stored payment ids are hex with no dashes. `PendingPayment.payment_id` is a
`uuid.UUID` and serialises with them; `_payment_view` was handing back the raw
string. Same id, two spellings, one screen that never loads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from geekvpn.domain.payments.enums import PaymentMethod, PaymentState
from geekvpn.infrastructure.bot.checkout import payment_uuid
from geekvpn.presentation.api.routers.miniapp import _payment_view

pytestmark = pytest.mark.integration

STORED = "b68447b886844445b12a7ff3691a810c"


def _payment() -> SimpleNamespace:
    return SimpleNamespace(
        id=STORED,
        amount=SimpleNamespace(amount=200_000),
        method=PaymentMethod.CARD,
        state=PaymentState.AWAITING_PROOF,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        expires_at=None,
        metadata={},
    )


def _scope() -> SimpleNamespace:
    return SimpleNamespace(gateways=SimpleNamespace(has=lambda key: False))


def test_the_list_spells_the_id_the_way_checkout_does() -> None:
    """`_to_pending` parses it; this must too, or the two never match."""
    view = _payment_view(_payment(), _scope())

    assert view["payment_id"] == payment_uuid(STORED)
    assert str(view["payment_id"]) == "b68447b8-8684-4445-b12a-7ff3691a810c"


def test_the_id_is_the_one_the_route_can_look_up() -> None:
    """`tests/unit/bot/test_payment_id_round_trip.py` owns the conversion
    itself; this is only that the list endpoint uses it."""
    view = _payment_view(_payment(), _scope())

    assert view["payment_id"].hex == STORED
