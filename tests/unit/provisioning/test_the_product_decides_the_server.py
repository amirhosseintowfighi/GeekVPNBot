"""A product bound to a server is delivered on that server and no other.

The binding was stored, shown in the admin panel and required before a
product could be published - and provisioning never read it. A customer who
bought the German product was put on whichever server had room first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from geekvpn.application.provisioning import panel_id_for
from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.errors import NoCapacityAvailable
from geekvpn.domain.provisioning.order import Order
from tests.unit.provisioning.fakes import (
    FakePanel,
    FakePanelProvider,
    FrozenClock,
    InMemoryNodes,
    InMemoryOrders,
    InMemorySubscriptions,
    RecordingPublisher,
    SequentialIds,
    node,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
PRODUCT = uuid.uuid4()


class Products:
    def __init__(self, bound_to: str | None) -> None:
        self.panel_id = panel_id_for(bound_to) if bound_to else None

    async def get(self, product_id: uuid.UUID) -> object:
        return SimpleNamespace(id=product_id, panel_id=self.panel_id)


def service(bound_to: str | None, *nodes: object) -> tuple[ProvisioningService, Order]:
    order = Order.place(
        "ord-1",
        number="1405-0001",
        user_id=777,
        plan_id=str(uuid.uuid4()),
        plan_name_fa="آلمان ماهانه",
        duration_days=30,
        list_price=Money(300_000),
        total=Money(300_000),
        product_id=str(PRODUCT),
        now=NOW,
    )
    order.mark_paid(at=NOW, invoice_id="inv-1")
    return (
        ProvisioningService(
            orders=InMemoryOrders(order),
            subscriptions=InMemorySubscriptions(),
            nodes=InMemoryNodes(*nodes),  # type: ignore[arg-type]
            panels=FakePanelProvider(FakePanel()),
            clock=FrozenClock(NOW),
            ids=SequentialIds("sub"),
            events=RecordingPublisher(),
            products=Products(bound_to),  # type: ignore[arg-type]
        ),
        order,
    )


async def test_the_bound_server_is_used_even_when_another_comes_first() -> None:
    provisioning, order = service(
        "node-nl", node("node-de", sort_order=0), node("node-nl", sort_order=1)
    )

    subscription = await provisioning.provision(order.id)

    assert subscription.node_id == "node-nl"


async def test_a_full_bound_server_is_not_swapped_for_another() -> None:
    """Out of room is an operator's problem; the wrong country is a customer's."""
    provisioning, order = service(
        "node-nl", node("node-de"), node("node-nl", capacity=1, account_count=1)
    )

    with pytest.raises(NoCapacityAvailable):
        await provisioning.provision(order.id)


async def test_an_unbound_product_goes_wherever_there_is_room() -> None:
    provisioning, order = service(None, node("node-de"), node("node-nl"))

    subscription = await provisioning.provision(order.id)

    assert subscription.node_id in {"node-de", "node-nl"}
