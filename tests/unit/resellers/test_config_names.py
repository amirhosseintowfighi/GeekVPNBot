"""A reseller's configs carry the reseller's name, not ours.

A customer sees the panel username on their client app; for a reseller's
customer "gv14050042" names a shop they never heard of. The reseller picks a
prefix and a suffix, and every account sold through them is named with it.

The name must still be derived from the order alone: a retry that asked for a
different username would create a second account on the panel.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.provisioning.provisioning_service import (
    ProvisioningService,
    username_for,
)
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.resellers import Reseller
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
from tests.unit.provisioning.test_provisioning_service import NOW, paid_order

pytestmark = pytest.mark.unit


def _reseller() -> Reseller:
    return Reseller(id=uuid.uuid4(), admin_id=uuid.uuid4(), name_fa="نمایندگی شمال")


def test_without_a_choice_the_platform_prefix_is_used() -> None:
    assert username_for(paid_order(number="1405-0042")) == "gv14050042"


def test_the_prefix_and_suffix_wrap_the_order_number() -> None:
    order = paid_order(number="1405-0042")

    assert username_for(order, prefix="north", suffix="_vip") == "north14050042_vip"


def test_a_reseller_name_is_lowercased() -> None:
    reseller = _reseller()

    reseller.set_config_name(prefix="North", suffix="VIP")

    assert (reseller.config_prefix, reseller.config_suffix) == ("north", "vip")


def test_blank_clears_the_choice() -> None:
    reseller = _reseller()
    reseller.set_config_name(prefix="north", suffix="x")

    reseller.set_config_name(prefix=" ", suffix="")

    assert (reseller.config_prefix, reseller.config_suffix) == (None, None)


@pytest.mark.parametrize(
    "prefix",
    ["نماینده", "a b", "north-shop", "abcdefghijk", "1north"],
)
def test_a_name_a_panel_would_refuse_is_refused_here(prefix: str) -> None:
    with pytest.raises(ValueError):
        _reseller().set_config_name(prefix=prefix, suffix=None)


def test_a_suffix_may_start_with_a_digit() -> None:
    reseller = _reseller()

    reseller.set_config_name(prefix=None, suffix="2")

    assert reseller.config_suffix == "2"


def _service(
    order: Order, panel: FakePanel, names: dict[str, tuple[str, str]]
) -> ProvisioningService:
    async def config_name(o: Order) -> tuple[str | None, str | None]:
        return names.get(o.id, (None, None))

    return ProvisioningService(
        orders=InMemoryOrders(order),
        subscriptions=InMemorySubscriptions(),
        nodes=InMemoryNodes(node("node-de")),
        panels=FakePanelProvider(panel),
        clock=FrozenClock(NOW),
        ids=SequentialIds("sub"),
        events=RecordingPublisher(),
        config_name=config_name,
    )


@pytest.mark.asyncio
async def test_a_resellers_order_is_created_under_the_resellers_name() -> None:
    order = paid_order(number="1405-0042")
    panel = FakePanel()
    service = _service(order, panel, {order.id: ("north", "")})

    subscription = await service.provision(order.id)

    assert subscription.remote_username == "north14050042"
    assert panel.created[0].username == "north14050042"


@pytest.mark.asyncio
async def test_an_order_from_no_reseller_keeps_the_platform_name() -> None:
    order = paid_order(number="1405-0042")
    panel = FakePanel()
    service = _service(order, panel, {})

    subscription = await service.provision(order.id)

    assert subscription.remote_username == "gv14050042"


def test_the_portal_form_refuses_what_the_aggregate_would() -> None:
    from pydantic import ValidationError

    from geekvpn.presentation.api.routers.reseller import ConfigNameRequest

    with pytest.raises(ValidationError):
        ConfigNameRequest.model_validate({"configPrefix": "north-shop"})
    blank = ConfigNameRequest.model_validate({"configPrefix": "", "configSuffix": ""})
    assert (blank.config_prefix, blank.config_suffix) == ("", "")


def test_the_scope_hands_provisioning_the_sellers_name() -> None:
    """Reachability: without this the prefix is stored and never used."""
    import inspect

    from geekvpn.infrastructure.di import scope

    source = inspect.getsource(scope.RequestScope.provisioning.func)  # type: ignore[attr-defined]
    assert "config_name=self._config_name" in source
