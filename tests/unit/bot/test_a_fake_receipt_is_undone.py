"""An approved receipt that turns out to be forged can be undone from the bot."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.presentation.bot.handlers import admin
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui.callbacks import AdminCB

pytestmark = pytest.mark.unit

CUSTOMER = 4242


class Query:
    def __init__(self) -> None:
        self.message = None

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        return None


class Customer:
    def __init__(self) -> None:
        self.reason: str | None = None
        self.telegram_id = CUSTOMER

    def suspend(self, *, reason: str) -> None:
        self.reason = reason


def scope(*, has_service: bool, customer: Customer) -> Any:
    revoked: list[str] = []

    async def get_by_order(order_id: str) -> Any:
        return SimpleNamespace(id="sub-9") if has_service else None

    async def revoke(sub_id: str, *, reason_fa: str) -> None:
        revoked.append(sub_id)

    async def by_telegram(telegram_id: int, *, reseller_id: Any = None) -> Customer:
        return customer

    async def update(user: Any) -> None:
        return None

    async def commit() -> None:
        return None

    async def remove_from_channels(telegram_id: int) -> int:
        return 0

    return SimpleNamespace(
        revoked=revoked,
        reseller=None,
        subscriptions=SimpleNamespace(get_by_order=get_by_order),
        subscription_admin=SimpleNamespace(revoke=revoke),
        users=SimpleNamespace(get_by_telegram_id=by_telegram, update=update),
        session=SimpleNamespace(commit=commit),
        remove_from_channels=remove_from_channels,
    )


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"screens": [], "reversed": []}

    async def guard(scope: Any, user: Any) -> Any:
        return object()

    async def edit(query: Any, body: str, *, markup: Any = None) -> None:
        seen["screens"].append(body)

    async def read(container: Any, work: Any) -> Any:
        return seen["found"]

    async def mutate(container: Any, work: Any) -> None:
        seen["reversed"].append("wallet")

    monkeypatch.setattr(admin, "_guard", guard)
    monkeypatch.setattr(admin, "safe_edit", edit)
    monkeypatch.setattr(admin, "read_scope", read)
    monkeypatch.setattr(admin, "mutate_scope", mutate)
    return seen


async def run(wired: dict[str, Any], s: Any) -> None:
    await admin.on_fake_confirmed(
        Query(),  # type: ignore[arg-type]
        AdminCB(action="fake_ok", ref="pay-1"),
        container=object(),  # type: ignore[arg-type]
        scope=s,
        user=SimpleNamespace(telegram_id=1),
    )


async def test_a_purchase_loses_its_service_and_the_sender_is_suspended(
    wired: dict[str, Any],
) -> None:
    wired["found"] = (CUSTOMER, "order-1", 300_000)
    customer = Customer()
    s = scope(has_service=True, customer=customer)

    await run(wired, s)

    assert s.revoked == ["sub-9"]
    assert customer.reason == A.FAKE_REASON
    assert A.FAKE_SERVICE_REMOVED in wired["screens"][-1]


async def test_a_top_up_has_its_credit_taken_back(wired: dict[str, Any]) -> None:
    wired["found"] = (CUSTOMER, None, 500_000)
    customer = Customer()

    await run(wired, scope(has_service=False, customer=customer))

    assert wired["reversed"] == ["wallet"]
    assert customer.reason == A.FAKE_REASON
    assert A.FAKE_TOPUP_REVERSED in wired["screens"][-1]
