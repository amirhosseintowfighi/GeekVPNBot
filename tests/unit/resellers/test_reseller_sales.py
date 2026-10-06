"""A reseller selling a package, or handing out a test account.

The sale path had two faults that each made every sale fail: the order went
in without the plan's product (a NOT NULL column) and it went to the panel
while still pending, which the order refuses to leave for provisioning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from geekvpn.application.provisioning.free_trial import TrialTerms
from geekvpn.application.resellers.sales import ResellerSalesService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.resellers import Reseller
from geekvpn.domain.resellers.errors import TrialLimitReached

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
PRODUCT = uuid.uuid4()


@dataclass
class _Plan:
    id: uuid.UUID
    product_id: uuid.UUID = PRODUCT
    name_fa: str = "یک ماهه"
    base_price: Money = Money(200_000)
    duration_days: int = 30
    device_limit: int = 2
    quota_gib: int | None = 50


class _Resellers:
    def __init__(self, reseller: Reseller) -> None:
        self.reseller = reseller
        self.charged: list[Money] = []
        self.refunded: list[Money] = []

    async def get(self, reseller_id: uuid.UUID) -> Reseller:
        return self.reseller

    async def charge_for_sale(self, reseller_id: uuid.UUID, *, amount: Money, description_fa: str) -> Reseller:
        self.charged.append(amount)
        self.reseller.balance_amount -= amount.amount
        return self.reseller

    async def refund_sale(self, reseller_id: uuid.UUID, *, amount: Money, **_: Any) -> None:
        self.refunded.append(amount)


class _Plans:
    def __init__(self, plan: _Plan) -> None:
        self.plan = plan

    async def get(self, plan_id: uuid.UUID) -> _Plan | None:
        return self.plan if plan_id == self.plan.id else None


@dataclass
class _Orders:
    rows: dict[str, Order] = field(default_factory=dict)

    async def place(self, **fields: Any) -> Order:
        number = f"1405-{len(self.rows) + 1:04d}"
        fields.pop("jalali_year")
        order = Order.place(f"ord-{len(self.rows) + 1}", number=number, now=NOW, **fields)
        self.rows[order.id] = order
        return order

    async def update(self, order: Order) -> None:
        self.rows[order.id] = order

    async def get(self, order_id: str) -> Order | None:
        return self.rows.get(order_id)


@dataclass
class _Subscription:
    id: str
    subscription_url: str | None
    remote_username: str
    expires_at: datetime


class _Provisioning:
    def __init__(self, orders: _Orders) -> None:
        self.orders = orders

    async def provision(self, order_id: str, **_: Any) -> _Subscription:
        order = self.orders.rows[order_id]
        # What the real service does first, and what refused a pending order.
        order.start_provisioning()
        return _Subscription("sub-1", "https://x/sub", "gv1", NOW)


class _FailingProvisioning(_Provisioning):
    async def provision(self, order_id: str, **_: Any) -> _Subscription:
        order = self.orders.rows[order_id]
        order.start_provisioning()
        order.fail(reason="panel_unreachable")
        raise RuntimeError("panel down")


class _Clock:
    def now(self) -> datetime:
        return NOW


def _build(
    *, trial_limit: int | None = None, given: int = 0, failing: bool = False
) -> tuple[ResellerSalesService, _Orders, _Resellers, _Plan]:
    reseller = Reseller(
        id=uuid.uuid4(),
        admin_id=uuid.uuid4(),
        name_fa="نمایندگی شمال",
        balance_amount=1_000_000,
        trial_limit=trial_limit,
    )
    plan = _Plan(id=uuid.uuid4())
    orders = _Orders()
    resellers = _Resellers(reseller)

    async def trials_given(_: Reseller) -> int:
        return given

    async def terms() -> TrialTerms:
        return TrialTerms(traffic_mib=300, duration_days=1)

    service = ResellerSalesService(
        resellers=resellers,  # type: ignore[arg-type]
        plans=_Plans(plan),
        orders=orders,
        order_repository=orders,
        provisioning=(_FailingProvisioning if failing else _Provisioning)(orders),
        clock=_Clock(),
        jalali_year=1405,
        trials_given=trials_given,
        trial_terms=terms,
    )
    return service, orders, resellers, plan


@pytest.mark.asyncio
async def test_a_sale_files_its_order_under_the_plans_product() -> None:
    service, orders, _, plan = _build()

    await service.sell(reseller_id=uuid.uuid4(), plan_id=plan.id)

    (order,) = orders.rows.values()
    assert order.product_id == str(PRODUCT)


@pytest.mark.asyncio
async def test_a_sale_is_paid_before_it_reaches_the_panel() -> None:
    service, orders, _, plan = _build()

    sale = await service.sell(reseller_id=uuid.uuid4(), plan_id=plan.id)

    (order,) = orders.rows.values()
    assert order.state is OrderState.PROVISIONING
    assert sale.charged == Money(200_000)


@pytest.mark.asyncio
async def test_a_test_account_costs_the_reseller_nothing() -> None:
    service, orders, resellers, plan = _build()

    sale = await service.give_trial(reseller_id=uuid.uuid4(), plan_id=plan.id)

    (order,) = orders.rows.values()
    assert sale.charged == Money(0)
    assert resellers.charged == []
    assert order.source is OrderSource.TRIAL
    assert order.total == Money(0)


@pytest.mark.asyncio
async def test_a_test_account_has_the_trials_size_not_the_plans() -> None:
    service, orders, _, plan = _build()

    await service.give_trial(reseller_id=uuid.uuid4(), plan_id=plan.id)

    (order,) = orders.rows.values()
    assert (order.traffic_mib, order.duration_days, order.device_limit) == (300, 1, 1)


@pytest.mark.asyncio
async def test_a_reseller_at_their_trial_limit_is_refused() -> None:
    service, orders, _, plan = _build(trial_limit=3, given=3)

    with pytest.raises(TrialLimitReached):
        await service.give_trial(reseller_id=uuid.uuid4(), plan_id=plan.id)
    assert orders.rows == {}


@pytest.mark.asyncio
async def test_no_limit_means_as_many_as_they_like() -> None:
    service, _, _, plan = _build(trial_limit=None, given=10_000)

    sale = await service.give_trial(reseller_id=uuid.uuid4(), plan_id=plan.id)

    assert sale.remote_username == "gv1"


def test_a_negative_trial_limit_is_refused() -> None:
    reseller = Reseller(id=uuid.uuid4(), admin_id=uuid.uuid4(), name_fa="x")

    with pytest.raises(ValueError):
        reseller.set_trial_limit(-1)


@pytest.mark.asyncio
async def test_a_refunded_sale_is_not_left_for_the_retry_queue_to_deliver() -> None:
    """The bot commits after a failed sale: the refund, and the failed order.
    Left FAILED, the worker would deliver it later - a free service."""
    service, orders, resellers, plan = _build(failing=True)

    with pytest.raises(RuntimeError):
        await service.sell(reseller_id=uuid.uuid4(), plan_id=plan.id)

    (order,) = orders.rows.values()
    assert resellers.refunded == [Money(200_000)]
    assert order.state is OrderState.CANCELLED
