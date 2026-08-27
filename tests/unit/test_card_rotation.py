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
    """Just enough of a `Session` for `session.execute(stmt).scalars().all()`.

    The registry asks two questions now - cards, then crypto addresses - and a
    fake that answered both with the same rows registered a crypto gateway
    whose address was a card number. Answering by call order is enough here and
    keeps the fake honest about there being two queries.
    """

    def __init__(self, *cards: Any, crypto: list[Any] | None = None) -> None:
        self._cards = list(cards)
        self._crypto = list(crypto or [])

    def execute(self, stmt: Any) -> Any:
        # Answered by which table the statement names, not by call order: the
        # rotation test builds the registry forty times against one session,
        # and a fake that answered in turn would run out after the first.
        wants_crypto = "crypto" in str(stmt).lower()
        rows = self._crypto if wants_crypto else self._cards
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


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


def crypto(address: str, network: str = "trc20") -> SimpleNamespace:
    return SimpleNamespace(address=address, network=network, asset="USDT")


def test_a_crypto_address_becomes_a_working_button():
    """`CryptoTransferGateway` existed since the payment layer was written,
    with tests, and nothing ever constructed it.

    So the bot offered "pay with crypto" and answered everyone who tapped it
    with a generic apology - there was nowhere to read an address from. A class
    only its own test calls is the failure this project keeps having.
    """
    registry = build_gateway_registry(Session(crypto=[crypto("TXyz")]))

    gateway = registry.get("crypto")
    assert gateway.address == "TXyz"
    assert gateway.network == "trc20"


def test_no_address_means_no_crypto_button():
    """Same rule as cards: better to not offer it than to offer a button that
    sends money nowhere."""
    registry = build_gateway_registry(Session())

    with pytest.raises(GatewayNotRegistered):
        registry.get("crypto")


def test_crypto_addresses_rotate_like_cards():
    session = Session(crypto=[crypto("TAaa"), crypto("TBbb")])

    seen = {build_gateway_registry(session).get("crypto").address for _ in range(40)}

    assert seen == {"TAaa", "TBbb"}


def test_cards_and_crypto_do_not_borrow_each_other_rows():
    """A registry that answered both questions from one list registered a
    crypto gateway whose address was a card number - which is a customer told
    to send USDT to sixteen digits."""
    session = Session(card("6037-1111"), crypto=[crypto("TXyz")])
    registry = build_gateway_registry(session)

    assert registry.get("card").card_number == "6037-1111"
    assert registry.get("crypto").address == "TXyz"
