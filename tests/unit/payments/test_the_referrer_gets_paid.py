"""The referrer is paid when the person they invited buys.

The other half of a programme the bot advertised from the day it shipped.
`referral_accruals` computed both sides of it into every `PriceQuote` and
nothing ever read the result, so «۱۰٪ از اولین خرید دوستت» was a promise no
wallet ever kept.

The tests that matter here are the ones about paying *once*: an event
re-delivered after a retry, and a second order from the same customer.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.payments.referral_rewards import (
    KIND,
    ReferralEdge,
    ReferralRewards,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.rewards import ReferralPolicy

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)
REFERRER, INVITEE = 111, 222


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Paid:
    """What `OrderPaid` looks like to a subscriber."""

    name = "provisioning.order.paid.v1"

    def __init__(
        self, order_id: str = "o-1", user_id: int = INVITEE, total: int = 200_000
    ) -> None:
        self.order_id = order_id
        self.user_id = user_id
        self.total = total


class Ledger:
    def __init__(self, edge: ReferralEdge | None) -> None:
        self.edge = edge
        self.settled: list[dict] = []

    def edge_for_invitee(self, invitee_telegram_id: int) -> ReferralEdge | None:
        if self.edge is None or self.edge.invitee_telegram_id != invitee_telegram_id:
            return None
        return self.edge

    def settle(self, **kwargs) -> None:
        self.settled.append(kwargs)
        # What the real one does: the stamp is written once.
        if self.edge is not None and self.edge.converted_at is None:
            self.edge = ReferralEdge(
                referrer_telegram_id=self.edge.referrer_telegram_id,
                invitee_telegram_id=self.edge.invitee_telegram_id,
                converted_at=kwargs["at"],
            )


class Wallets:
    def __init__(self, *, raises: bool = False) -> None:
        self.credits: list[dict] = []
        self._raises = raises

    def credit_reward(self, **kwargs) -> None:
        if self._raises:
            raise RuntimeError("wallet down")
        self.credits.append(kwargs)


def _edge(*, converted: datetime | None = None) -> ReferralEdge:
    return ReferralEdge(
        referrer_telegram_id=REFERRER, invitee_telegram_id=INVITEE, converted_at=converted
    )


def _service(ledger: Ledger, wallets: Wallets, policy: ReferralPolicy | None = None):
    return ReferralRewards(
        ledger=ledger,
        wallets=wallets,
        policy=lambda: policy or ReferralPolicy(),
        clock=FixedClock(),
    )


def test_the_referrer_is_credited_a_share_of_the_first_purchase():
    ledger, wallets = Ledger(_edge()), Wallets()

    _service(ledger, wallets).on_order_paid(Paid(total=200_000))

    assert len(wallets.credits) == 1
    assert wallets.credits[0]["user_id"] == REFERRER
    # The default policy is 1000 bps.
    assert wallets.credits[0]["amount"] == Money(20_000)
    assert wallets.credits[0]["kind"] is KIND


def test_the_conversion_is_recorded_against_the_edge():
    """"Invited" and "converted" are two different numbers on the operator's
    report, and the second one was always zero."""
    ledger = Ledger(_edge())

    _service(ledger, Wallets()).on_order_paid(Paid(order_id="o-9", total=200_000))

    assert ledger.settled[0]["order_id"] == "o-9"
    assert ledger.settled[0]["paid"] == 200_000
    assert ledger.settled[0]["reward"] == 20_000


def test_a_customer_nobody_invited_costs_nothing():
    ledger, wallets = Ledger(None), Wallets()

    _service(ledger, wallets).on_order_paid(Paid())

    assert wallets.credits == []
    assert ledger.settled == []


def test_a_second_order_pays_the_recurring_rate_not_the_first_one_again():
    """Zero by default: lifetime revenue sharing is an obligation that is very
    hard to withdraw once advertised."""
    ledger, wallets = Ledger(_edge(converted=NOW)), Wallets()

    _service(ledger, wallets).on_order_paid(Paid(order_id="o-2", total=200_000))

    assert wallets.credits == []
    # Still recorded: the revenue this edge generated is the whole point of
    # the report, whether or not it paid a reward.
    assert ledger.settled[0]["paid"] == 200_000


def test_a_recurring_rate_is_honoured_when_one_is_set():
    ledger, wallets = Ledger(_edge(converted=NOW)), Wallets()
    policy = ReferralPolicy(recurring_bps=500)

    _service(ledger, wallets, policy).on_order_paid(Paid(total=200_000))

    assert wallets.credits[0]["amount"] == Money(10_000)


def test_the_ledger_entry_is_keyed_on_the_order():
    """The guard against paying twice for one purchase. The wallet holds a
    unique constraint on (user, kind, reference), so a re-delivered event
    collides with the row that is already there."""
    ledger, wallets = Ledger(_edge()), Wallets()

    _service(ledger, wallets).on_order_paid(Paid(order_id="o-7"))

    assert wallets.credits[0]["reference"] == "referral:o-7"


def test_a_switched_off_programme_pays_nothing():
    ledger, wallets = Ledger(_edge()), Wallets()

    _service(ledger, wallets, ReferralPolicy(enabled=False)).on_order_paid(Paid())

    assert wallets.credits == []


def test_the_cap_is_applied():
    ledger, wallets = Ledger(_edge()), Wallets()
    policy = ReferralPolicy(max_reward_per_order=Money(5_000))

    _service(ledger, wallets, policy).on_order_paid(Paid(total=1_000_000))

    assert wallets.credits[0]["amount"] == Money(5_000)


def test_a_free_order_pays_nothing():
    """A zero total is a trial or a fully discounted order. Ten percent of
    nothing is nothing, and settling it would count a conversion that brought
    no revenue."""
    ledger, wallets = Ledger(_edge()), Wallets()

    _service(ledger, wallets).on_order_paid(Paid(total=0))

    assert wallets.credits == []
    assert ledger.settled == []


def test_a_wallet_that_will_not_credit_does_not_break_the_delivery():
    """This runs after the money has moved and while the service is being
    built. A referrer's bonus is worth a log line, never an exception thrown
    into the path of a customer who has already paid."""
    ledger, wallets = Ledger(_edge()), Wallets(raises=True)

    _service(ledger, wallets).on_order_paid(Paid())

    assert ledger.settled == []


def test_an_event_of_the_wrong_shape_is_ignored():
    """Subscribers are typed loosely on purpose - see the module docstring -
    so the shape check is this service's own job."""
    ledger, wallets = Ledger(_edge()), Wallets()

    _service(ledger, wallets).on_order_paid(object())

    assert wallets.credits == []


# -- wired --------------------------------------------------------------------
#
# The reason this whole feature was dead: the calculation existed, was tested,
# and nothing subscribed to it. Structural, because that is the shape of the
# failure - a handler nobody registers looks identical to a working one from
# inside its own tests.


def test_the_handler_is_actually_subscribed() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "src/geekvpn/infrastructure/di/sync_scope.py"
    ).read_text(encoding="utf-8")

    assert "table[OrderPaid.name] = self._pay_referrer" in source
    assert "self.referral_rewards.on_order_paid(event)" in source


def test_the_quote_still_computes_the_same_rule() -> None:
    """The accruals on a `PriceQuote` predict what this service will pay. They
    are still unread by anything, but they are what the storefront would show
    a customer, so the two must not describe different programmes."""
    import uuid

    from geekvpn.domain.catalog.rewards import referral_accruals

    policy = ReferralPolicy()
    predicted = referral_accruals(
        paid=Money(200_000),
        buyer_id=uuid.uuid4(),
        referrer_id=uuid.uuid4(),
        policy=policy,
        is_first_purchase=True,
    )
    ledger, wallets = Ledger(_edge()), Wallets()

    _service(ledger, wallets, policy).on_order_paid(Paid(total=200_000))

    assert wallets.credits[0]["amount"] == predicted[0].amount
