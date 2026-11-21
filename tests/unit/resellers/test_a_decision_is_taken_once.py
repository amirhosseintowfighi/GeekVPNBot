"""A reseller's request is decided by one operator, once.

Approving a top-up read the request, saw "pending", credited the balance and
then wrote the decision - with nothing stopping a second caller doing the same
between the read and the write. Two operators on one queue, or one operator's
double tap (Telegram delivers it as two updates), both read "pending" and both
credited: the reseller was paid twice for one transfer. Approving an
application had the same shape and made two reseller accounts for one person.

The decision is now a claim - written only where the row still says pending -
and it is taken before anything else, in the same transaction. Whoever loses
the claim is told the request is no longer waiting and changes nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from geekvpn.application.resellers.applications import (
    PENDING as APP_PENDING,
)
from geekvpn.application.resellers.applications import (
    ApplicationNotFound,
    ApplicationView,
    ResellerApplications,
)
from geekvpn.application.resellers.topups import (
    PENDING,
    ResellerTopups,
    TopupNotFound,
    TopupView,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _StaleTopups:
    """Every caller reads "pending"; only the first claim succeeds."""

    def __init__(self, topup: TopupView) -> None:
        self.topup = topup
        self.claimed = False

    async def get(self, topup_id: uuid.UUID) -> TopupView | None:
        return self.topup

    async def decide(self, topup_id: uuid.UUID, **_: Any) -> bool:
        if self.claimed:
            return False
        self.claimed = True
        return True


class _Resellers:
    def __init__(self) -> None:
        self.credits: list[int] = []
        self.created = 0

    async def adjust_credit(self, reseller_id: uuid.UUID, *, amount: int, **_: Any) -> None:
        self.credits.append(amount)

    async def create(self, **_: Any) -> Any:
        self.created += 1
        reseller = type("R", (), {"id": uuid.uuid4(), "admin_id": uuid.uuid4()})()
        return type("C", (), {"reseller": reseller, "username": "x"})()


def _topup() -> TopupView:
    return TopupView(
        id=uuid.uuid4(),
        reseller_id=uuid.uuid4(),
        reseller_name_fa="فروشگاه",
        amount=500_000,
        note_fa=None,
        receipt_file_id=None,
        state=PENDING,
        created_at=NOW,
    )


async def test_a_top_up_approved_twice_is_credited_once() -> None:
    topup = _topup()
    resellers = _Resellers()
    service = ResellerTopups(
        topups=_StaleTopups(topup),  # type: ignore[arg-type]
        resellers=resellers,  # type: ignore[arg-type]
        clock=_Clock(),
    )

    await service.approve(topup.id)
    with pytest.raises(TopupNotFound):
        await service.approve(topup.id)

    assert resellers.credits == [500_000]


async def test_a_top_up_rejected_after_approval_stays_approved() -> None:
    topup = _topup()
    store = _StaleTopups(topup)
    service = ResellerTopups(
        topups=store,  # type: ignore[arg-type]
        resellers=_Resellers(),  # type: ignore[arg-type]
        clock=_Clock(),
    )

    await service.approve(topup.id)
    with pytest.raises(TopupNotFound):
        await service.reject(topup.id)


class _StaleApplications:
    def __init__(self, application: ApplicationView) -> None:
        self.application = application
        self.claimed = False

    async def get(self, application_id: uuid.UUID) -> ApplicationView | None:
        return self.application

    async def decide(self, application_id: uuid.UUID, **_: Any) -> bool:
        if self.claimed:
            return False
        self.claimed = True
        return True

    async def attach_reseller(self, application_id: uuid.UUID, reseller_id: uuid.UUID) -> None:
        pass


class _Tokens:
    async def issue(self, *_: Any, **__: Any) -> None:
        pass


class _Hasher:
    def hash(self, value: str) -> str:
        return "h"


async def test_an_application_approved_twice_makes_one_reseller() -> None:
    application = ApplicationView(
        id=uuid.uuid4(),
        telegram_id=6215538602,
        name_fa="فروشگاه",
        contact_fa="@shop",
        note_fa=None,
        state=APP_PENDING,
        created_at=NOW,
    )
    resellers = _Resellers()
    service = ResellerApplications(
        applications=_StaleApplications(application),  # type: ignore[arg-type]
        resellers=resellers,  # type: ignore[arg-type]
        setup_tokens=_Tokens(),  # type: ignore[arg-type]
        hasher=_Hasher(),  # type: ignore[arg-type]
        clock=_Clock(),
    )

    await service.approve(application.id)
    with pytest.raises(ApplicationNotFound):
        await service.approve(application.id)

    assert resellers.created == 1
