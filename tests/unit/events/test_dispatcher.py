"""The dispatcher is the piece two whole features were silently missing."""

from __future__ import annotations

from typing import Any

from geekvpn.infrastructure.events.dispatcher import (
    DispatchingEventPublisher,
    event_name,
)


class _Approved:
    name = "billing.payment.approved.v1"

    def __init__(self, payment_id: str = "pay-1") -> None:
        self.payment_id = payment_id

    def payload(self) -> dict[str, Any]:
        return {"payment_id": self.payment_id}


class _Unnamed:
    """No wire name, so it falls back to the class name."""


def test_a_handler_receives_the_event() -> None:
    seen: list[object] = []
    publisher = DispatchingEventPublisher({_Approved.name: seen.append})

    event = _Approved()
    publisher.publish_all([event])

    assert seen == [event]


def test_routing_is_by_wire_name_not_by_class() -> None:
    """So an outbox can route decoded JSON without importing the payment domain."""
    seen: list[object] = []
    publisher = DispatchingEventPublisher({"billing.payment.approved.v1": seen.append})

    publisher.publish_all([_Approved()])

    assert len(seen) == 1


def test_several_handlers_run_in_registration_order() -> None:
    order: list[str] = []
    publisher = DispatchingEventPublisher()
    publisher.subscribe(_Approved.name, lambda e: order.append("first"))
    publisher.subscribe(_Approved.name, lambda e: order.append("second"))

    publisher.publish_all([_Approved()])

    assert order == ["first", "second"]


def test_a_broken_handler_never_fails_the_operation() -> None:
    """Rolling back a captured payment because Telegram was down is not a trade
    we are willing to make."""
    survived: list[str] = []

    def explodes(event: object) -> None:
        raise RuntimeError("telegram is down")

    publisher = DispatchingEventPublisher()
    publisher.subscribe(_Approved.name, explodes)
    publisher.subscribe(_Approved.name, lambda e: survived.append("ran"))

    publisher.publish_all([_Approved()])

    assert survived == ["ran"]


def test_an_unhandled_event_is_not_an_error() -> None:
    publisher = DispatchingEventPublisher()

    publisher.publish_all([_Approved()])  # must not raise


def test_an_event_without_a_wire_name_falls_back_to_its_class() -> None:
    assert event_name(_Unnamed()) == "_Unnamed"
    assert event_name(_Approved()) == "billing.payment.approved.v1"


def test_an_event_whose_payload_raises_is_still_delivered() -> None:
    """Logging is best-effort; delivery is not."""

    class _Hostile:
        name = "billing.payment.approved.v1"

        def payload(self) -> dict[str, Any]:
            raise ValueError("nope")

    seen: list[object] = []
    publisher = DispatchingEventPublisher({_Hostile.name: seen.append})

    publisher.publish_all([_Hostile()])

    assert len(seen) == 1


def test_handlers_for_reports_what_is_wired() -> None:
    """Used by the wiring test that pins provisioning to PaymentApproved."""
    publisher = DispatchingEventPublisher({_Approved.name: lambda e: None})

    assert len(publisher.handlers_for(_Approved.name)) == 1
    assert publisher.handlers_for("nothing.here") == ()
