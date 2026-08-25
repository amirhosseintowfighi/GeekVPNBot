"""A receipt photo sent with no flow behind it must still reach its payment.

A card payment started in the Mini App ends with a button that closes the app.
The customer is then in the chat with no FSM state, so the photo they were
told to send matched only the catch-all handler and got "I did not understand
that". They had transferred the money and no way to prove it, and the payment
stayed in AWAITING_PROOF - a state the review queue does not show, so it was
invisible to the operator as well. Both halves of "nothing happens" came from
this one gap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.bot.read_models import PaymentMethod, PaymentState, PendingPayment
from geekvpn.presentation.bot.handlers.fallback import stray_receipt
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit


class Photo:
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id


class Message:
    """Just enough of an aiogram Message for this handler."""

    def __init__(self, photo: list[Photo] | None) -> None:
        self.photo = photo
        self.replies: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.replies.append(text)


class State:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


class Checkout:
    def __init__(self, pending: list[PendingPayment]) -> None:
        self._pending = pending
        self.attached: tuple[uuid.UUID, str] | None = None

    async def awaiting_proof(self, user_id: uuid.UUID) -> list[PendingPayment]:
        return self._pending

    async def attach_receipt(
        self, user_id: uuid.UUID, *, payment_id: uuid.UUID, file_id: str
    ) -> PendingPayment:
        self.attached = (payment_id, file_id)
        return self._pending[0]


class Services:
    def __init__(self, checkout: Checkout) -> None:
        self.checkout = checkout


class User:
    id = uuid.UUID(int=7)


def payment(reference: str = "1405-00009") -> PendingPayment:
    return PendingPayment(
        payment_id=uuid.uuid4(),
        reference=reference,
        amount=200_000,
        method=PaymentMethod.CARD,
        state=PaymentState.AWAITING_PROOF,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


async def run(pending: list[PendingPayment]) -> tuple[Message, Checkout, State]:
    message = Message([Photo("small"), Photo("largest")])
    checkout = Checkout(pending)
    state = State()
    await stray_receipt(message, state, Services(checkout), User())  # type: ignore[arg-type]
    return message, checkout, state


async def test_the_only_waiting_payment_gets_the_receipt() -> None:
    waiting = payment()
    message, checkout, state = await run([waiting])

    assert checkout.attached is not None
    assert checkout.attached[0] == waiting.payment_id
    assert state.cleared
    assert "1405-00009" in message.replies[0]


async def test_the_highest_resolution_photo_is_the_one_sent() -> None:
    """An operator has to read a reference number off it."""
    _, checkout, _ = await run([payment()])

    assert checkout.attached is not None
    assert checkout.attached[1] == "largest"


async def test_a_photo_with_nothing_waiting_is_explained_not_attached() -> None:
    message, checkout, _ = await run([])

    assert checkout.attached is None
    assert message.replies == [T.PAY_RECEIPT_NO_PENDING]


async def test_two_waiting_payments_are_never_guessed_between() -> None:
    """Attaching the wrong receipt gets the wrong order approved."""
    message, checkout, _ = await run([payment("A"), payment("B")])

    assert checkout.attached is None
    assert message.replies == [T.PAY_RECEIPT_AMBIGUOUS]
