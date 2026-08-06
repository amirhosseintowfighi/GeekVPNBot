"""Order lifecycle. The rules here decide whether a paying customer is stuck."""

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning import (
    IllegalOrderTransition,
    Order,
    OrderState,
    OrderValidationError,
)

NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def make_order(**kwargs):
    defaults = {
        "number": "GV-1405-000042",
        "user_id": 1001,
        "plan_id": "plan-90",
        "plan_name_fa": "گیک توربو ۹۰ روزه",
        "duration_days": 90,
        "list_price": Money(680_000),
        "total": Money(578_000),
        "now": NOW,
        "traffic_mib": 100 * 1024,
    }
    defaults.update(kwargs)
    return Order.place("ord-1", **defaults)


def test_placing_an_order_records_the_event_and_keeps_the_price_paid():
    order = make_order()
    assert order.state is OrderState.PENDING
    assert order.total == Money(578_000)
    # The discount must survive as data, not be recomputed from a plan that
    # may be repriced tomorrow.
    assert order.savings == Money(102_000)
    events = order.collect_events()
    assert [e.name for e in events] == ["provisioning.order.placed.v1"]
    assert events[0].payload()["total"] == 578_000


def test_the_happy_path_walks_pending_to_active():
    order = make_order()
    order.mark_paid(at=NOW, invoice_id="inv-9")
    assert order.state is OrderState.PAID
    assert order.invoice_id == "inv-9"
    order.start_provisioning()
    order.mark_active(subscription_id="sub-1", at=NOW + timedelta(minutes=1))
    assert order.state is OrderState.ACTIVE
    assert order.provisioned_at is not None
    names = [e.name for e in order.collect_events()]
    assert names == [
        "provisioning.order.placed.v1",
        "provisioning.order.paid.v1",
        "provisioning.order.provisioned.v1",
    ]


def test_paying_twice_is_refused_rather_than_absorbed():
    order = make_order()
    order.mark_paid(at=NOW)
    with pytest.raises(IllegalOrderTransition):
        order.mark_paid(at=NOW)


def test_a_failed_order_can_be_retried_because_the_money_is_already_ours():
    order = make_order()
    order.mark_paid(at=NOW)
    order.start_provisioning()
    order.fail(reason="panel timeout")
    assert order.state is OrderState.FAILED
    assert order.failure_reason == "panel timeout"
    order.start_provisioning()
    # The stale reason must not survive next to a fresh attempt.
    assert order.failure_reason is None
    order.mark_active(subscription_id="sub-2", at=NOW)
    assert order.state is OrderState.ACTIVE


def test_an_unpaid_order_cannot_be_provisioned():
    order = make_order()
    with pytest.raises(IllegalOrderTransition):
        order.start_provisioning()


def test_a_cancelled_order_is_terminal():
    order = make_order()
    order.cancel()
    with pytest.raises(IllegalOrderTransition):
        order.mark_paid(at=NOW)


def test_a_zero_day_order_is_rejected_at_construction():
    with pytest.raises(OrderValidationError):
        make_order(duration_days=0)


def test_unlimited_orders_carry_no_traffic_figure():
    order = make_order(traffic_mib=None)
    assert order.is_unlimited is True


def test_restore_rebuilds_without_emitting_anything():
    order = Order.restore(
        "ord-9",
        number="GV-1405-000099",
        user_id=1001,
        plan_id="plan-30",
        plan_name_fa="گیک دایرکت",
        duration_days=30,
        list_price=Money(300_000),
        total=Money(300_000),
        placed_at=NOW,
        state=OrderState.ACTIVE,
    )
    assert order.state is OrderState.ACTIVE
    assert order.collect_events() == []
