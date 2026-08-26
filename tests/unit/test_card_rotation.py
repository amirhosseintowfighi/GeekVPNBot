"""Several destination cards, used in turn.

A shop that takes every transfer on one card collects a bank's attention and,
eventually, a frozen account. Operators therefore enter more than one, and the
registry has to actually spread traffic across them - a second card that never
appears is the same as no second card.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.domain.payments.errors import GatewayNotRegistered
from geekvpn.infrastructure.di.sync_scope import build_gateway_registry

pytestmark = pytest.mark.unit


class Session:
    """Just enough of a `Session` for `session.execute(stmt).scalars().all()`."""

    def __init__(self, *cards: Any) -> None:
        self._cards = list(cards)

    def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self._cards))


def card(number: str) -> SimpleNamespace:
    return SimpleNamespace(
        card_number=number,
        holder_fa="علی",
        bank_fa="ملی",
    )


def _chosen(session: Session) -> str:
    gateway = build_gateway_registry(session).get("card")
    return gateway.card_number


def test_a_second_card_is_actually_used():
    """The registry used to take the first row and stop, so every transfer in
    the shop's life landed on one account no matter how many were entered."""
    session = Session(card("6037-1111"), card("5892-2222"))
    seen = {_chosen(session) for _ in range(40)}

    assert seen == {"6037-1111", "5892-2222"}


def test_one_card_is_still_the_card():
    assert _chosen(Session(card("6037-1111"))) == "6037-1111"


def test_no_card_means_no_card_gateway():
    """A fresh install has none. Better than offering a button that sends
    money nowhere."""
    registry = build_gateway_registry(Session())

    assert registry.get("wallet") is not None
    with pytest.raises(GatewayNotRegistered):
        registry.get("card")
