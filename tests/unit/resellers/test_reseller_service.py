"""Credit only moves through the service, and every movement leaves a row.

A balance is a number somebody will eventually dispute. The only useful answer
to "where did my credit go" is the list of things that changed it, so a balance
that moved without writing a ledger row is a bug even when the arithmetic is
right.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from geekvpn.application.resellers.service import (
    REFUND,
    SALE,
    TOPUP,
    ResellerService,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.resellers import InsufficientCredit, Reseller, ResellerNotFound
from geekvpn.domain.resellers.enums import ResellerStatus

pytestmark = pytest.mark.unit

EPOCH = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
PLAN = uuid.uuid4()


class Clock:
    def now(self) -> datetime:
        return EPOCH


@dataclass
class Entry:
    id: str
    amount: int
    balance_after: int
    kind: str
    description_fa: str
    reference: str | None
    occurred_at: datetime


class Repository:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Reseller] = {}
        self.ledger: list[Entry] = []

    async def get(self, reseller_id: uuid.UUID) -> Reseller | None:
        return self.rows.get(reseller_id)

    async def get_by_admin(self, admin_id: uuid.UUID) -> Reseller | None:
        return next((r for r in self.rows.values() if r.admin_id == admin_id), None)

    async def list_all(self):
        return list(self.rows.values())

    async def add(self, reseller: Reseller) -> None:
        self.rows[reseller.id] = reseller

    async def save(self, reseller: Reseller) -> None:
        self.rows[reseller.id] = reseller

    async def record(self, **kwargs: Any) -> None:
        self.ledger.append(
            Entry(
                id=kwargs["entry_id"],
                amount=kwargs["amount"],
                balance_after=kwargs["balance_after"],
                kind=kwargs["kind"],
                description_fa=kwargs["description_fa"],
                reference=kwargs.get("reference"),
                occurred_at=kwargs["occurred_at"],
            )
        )

    async def history(self, reseller_id: uuid.UUID, *, limit: int = 50):
        return list(reversed(self.ledger))[:limit]


class Admins:
    """Just enough of `ManageAdmins` to create a login."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        return type("Profile", (), {"id": uuid.uuid4(), "username": kwargs["username"]})()


class Prices:
    def __init__(self, price: int = 680_000) -> None:
        self._price = price

    async def list_price(self, plan_id: uuid.UUID) -> Money | None:
        return Money(self._price) if plan_id == PLAN else None


class World:
    def __init__(self) -> None:
        self.repo = Repository()
        self.admins = Admins()
        self.service = ResellerService(
            resellers=self.repo,
            admins=self.admins,  # type: ignore[arg-type]
            prices=Prices(),
            clock=Clock(),
        )

    async def make(self, *, discount: int = 30, balance: int = 0) -> Reseller:
        created = await self.service.create(
            username="north", name_fa="نمایندگی شمال", discount_percent=discount
        )
        reseller = created.reseller
        reseller.balance_amount = balance
        await self.repo.save(reseller)
        return reseller


# -- creation ---------------------------------------------------------------


async def test_creating_a_reseller_creates_the_login_beside_it():
    """Either alone is a broken state: an account with the role and no record
    signs in and can do nothing, and a record with no account is a price list
    nobody can reach."""
    world = World()

    created = await world.service.create(username="north", name_fa="شمال")

    assert world.admins.created[0]["username"] == "north"
    assert created.reseller.admin_id is not None
    assert await world.repo.get(created.reseller.id) is not None


async def test_the_generated_password_is_long_and_returned_once():
    world = World()

    created = await world.service.create(username="north", name_fa="شمال")

    assert len(created.password) >= 24
    # And it is what the login was created with, not a second value.
    assert world.admins.created[0]["password"] == created.password


async def test_a_reseller_is_found_by_the_login_that_signed_in():
    """The whole of reseller scoping: the token says which admin account is
    calling, and this says which rows are theirs."""
    world = World()
    created = await world.service.create(username="north", name_fa="شمال")

    found = await world.service.for_admin(created.reseller.admin_id)

    assert found.id == created.reseller.id


async def test_an_ordinary_admin_is_not_a_reseller():
    world = World()

    with pytest.raises(ResellerNotFound):
        await world.service.for_admin(uuid.uuid4())


# -- credit -----------------------------------------------------------------


async def test_a_top_up_is_recorded():
    world = World()
    reseller = await world.make()

    await world.service.adjust_credit(
        reseller.id, amount=1_000_000, description_fa="شارژ اولیه"
    )

    assert world.repo.rows[reseller.id].balance_amount == 1_000_000
    assert world.repo.ledger[-1].kind == TOPUP
    assert world.repo.ledger[-1].balance_after == 1_000_000


async def test_a_sale_is_recorded_against_what_was_sold():
    """The reference is how a reseller reconciles a charge with a customer."""
    world = World()
    reseller = await world.make(balance=1_000_000)

    await world.service.charge_for_sale(
        reseller.id, amount=Money(476_000), description_fa="سه ماهه", reference="sub-1"
    )

    entry = world.repo.ledger[-1]
    assert entry.kind == SALE
    assert entry.amount == -476_000
    assert entry.reference == "sub-1"
    assert entry.balance_after == 524_000


async def test_a_sale_beyond_the_balance_changes_nothing():
    """Raised before anything is provisioned, and the ledger stays clean - a
    refused sale that still wrote a row would be a balance nobody can explain."""
    world = World()
    reseller = await world.make(balance=100_000)

    with pytest.raises(InsufficientCredit):
        await world.service.charge_for_sale(
            reseller.id, amount=Money(476_000), description_fa="سه ماهه"
        )

    assert world.repo.rows[reseller.id].balance_amount == 100_000
    assert world.repo.ledger == []


async def test_a_failed_provision_gives_the_credit_back():
    """The charge happens before the panel call so a reseller cannot spend a
    balance they do not have. That ordering means a panel that refuses leaves
    money debited for nothing, and this is the other half."""
    world = World()
    reseller = await world.make(balance=1_000_000)
    await world.service.charge_for_sale(
        reseller.id, amount=Money(476_000), description_fa="سه ماهه", reference="sub-1"
    )

    await world.service.refund_sale(
        reseller.id, amount=Money(476_000), description_fa="پنل جواب نداد", reference="sub-1"
    )

    assert world.repo.rows[reseller.id].balance_amount == 1_000_000
    assert world.repo.ledger[-1].kind == REFUND
    # Both halves are visible, rather than the charge disappearing.
    assert len(world.repo.ledger) == 2


async def test_an_operator_can_deduct_by_hand():
    world = World()
    reseller = await world.make(balance=1_000_000)

    await world.service.adjust_credit(
        reseller.id, amount=-200_000, description_fa="تسویه"
    )

    assert world.repo.rows[reseller.id].balance_amount == 800_000


async def test_a_deduction_may_take_a_reseller_into_arrears():
    """Deliberately allowed, and the consequence is not a refusal.

    A reseller whose balance has gone under has their customers' services
    suspended until it is positive again - that suspension is the credit limit
    this platform enforces, in place of a number nobody would keep up to date.
    Refusing the deduction instead would leave an operator unable to record a
    settlement that has already happened.
    """
    world = World()
    reseller = await world.make(balance=100_000)

    await world.service.adjust_credit(
        reseller.id, amount=-200_000, description_fa="تسویه"
    )

    assert world.repo.rows[reseller.id].balance_amount == -100_000
    assert world.repo.rows[reseller.id].in_arrears
    # And it is on the record, with the balance it left behind.
    assert world.repo.ledger[-1].balance_after == -100_000


async def test_a_new_sale_is_still_refused_without_credit():
    """The two are different questions. An operator may record a debt; a
    reseller may not create one by buying something."""
    world = World()
    reseller = await world.make(balance=100_000)

    with pytest.raises(InsufficientCredit):
        await world.service.charge_for_sale(
            reseller.id, amount=Money(476_000), description_fa="سه ماهه"
        )


async def test_a_suspended_reseller_can_still_have_their_balance_corrected():
    """`charge` refuses on a suspended account, which is right for a sale and
    wrong for an operator fixing a mistake. Suspension stops selling, not
    accounting."""
    world = World()
    reseller = await world.make(balance=100_000)
    await world.service.update(reseller.id, status=ResellerStatus.SUSPENDED)

    await world.service.adjust_credit(
        reseller.id, amount=-50_000, description_fa="اصلاح"
    )

    assert world.repo.rows[reseller.id].balance_amount == 50_000


# -- pricing ----------------------------------------------------------------


async def test_a_quote_shows_both_prices():
    """A reseller decides what to charge their own customer from the gap."""
    world = World()
    reseller = await world.make(discount=30)

    quote = await world.service.quote(reseller.id, PLAN)

    assert quote is not None
    assert quote.list_price == Money(680_000)
    assert quote.reseller_price == Money(476_000)
    assert quote.saving == Money(204_000)


async def test_a_quote_for_a_package_that_is_gone_is_none():
    world = World()
    reseller = await world.make()

    assert await world.service.quote(reseller.id, uuid.uuid4()) is None


async def test_the_discount_cap_is_enforced_on_update_too():
    """Not only at construction: an edit is the likelier place for a typo."""
    world = World()
    reseller = await world.make()

    with pytest.raises(ValueError):
        await world.service.update(reseller.id, discount_percent=99)


# -- the consequence actually runs ------------------------------------------


class Arrears:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, bool]] = []

    async def apply(self, *, reseller_id: uuid.UUID, in_arrears: bool):
        self.calls.append((reseller_id, in_arrears))
        return None


async def test_a_deduction_into_arrears_suspends_the_customers():
    """The consequence is the credit limit. A balance that can go under with
    nothing watching is not a limit at all."""
    world = World()
    arrears = Arrears()
    world.service._arrears = arrears
    reseller = await world.make(balance=100_000)

    await world.service.adjust_credit(
        reseller.id, amount=-200_000, description_fa="تسویه"
    )

    assert arrears.calls == [(reseller.id, True)]


async def test_a_top_up_out_of_arrears_brings_them_back():
    world = World()
    arrears = Arrears()
    world.service._arrears = arrears
    reseller = await world.make(balance=-100_000)

    await world.service.adjust_credit(
        reseller.id, amount=300_000, description_fa="شارژ"
    )

    assert arrears.calls == [(reseller.id, False)]


async def test_it_runs_after_every_movement_not_only_a_crossing():
    """Crossing zero is not something this can detect reliably: a previous run
    may have failed on a node that was down, and re-reading the truth each time
    is what makes that self-healing rather than permanent."""
    world = World()
    arrears = Arrears()
    world.service._arrears = arrears
    reseller = await world.make(balance=1_000_000)

    await world.service.charge_for_sale(
        reseller.id, amount=Money(1), description_fa="x"
    )
    await world.service.refund_sale(reseller.id, amount=Money(1), description_fa="x")

    assert len(arrears.calls) == 2
    assert all(in_arrears is False for _, in_arrears in arrears.calls)
