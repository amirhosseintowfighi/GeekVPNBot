"""The product screen can say how much room its server has left."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.application.provisioning import panel_id_for
from geekvpn.presentation.bot.handlers.shop import capacity_line
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit


def scope(*, shown: bool, capacity: int, used: int, bound: bool = True) -> Any:
    async def get_setting(definition: Any) -> bool:
        return shown

    async def get_product(product_id: Any) -> Any:
        return SimpleNamespace(panel_id=panel_id_for("node-de") if bound else None)

    async def list_every() -> list[Any]:
        return [SimpleNamespace(id="node-de", capacity=capacity, account_count=used)]

    return SimpleNamespace(
        settings_service=SimpleNamespace(get=get_setting),
        catalog_products=SimpleNamespace(get=get_product),
        nodes=SimpleNamespace(list_every=list_every),
    )


async def test_room_left_is_shown_when_the_shop_wants_it() -> None:
    line = await capacity_line(scope(shown=True, capacity=100, used=40), uuid.uuid4())

    assert line == T.CAPACITY_LEFT.format(count="۶۰")


async def test_a_nearly_full_server_says_so() -> None:
    line = await capacity_line(scope(shown=True, capacity=100, used=95), uuid.uuid4())

    assert line == T.CAPACITY_LOW.format(count="۵")


async def test_a_full_server_says_so() -> None:
    assert await capacity_line(scope(shown=True, capacity=10, used=10), uuid.uuid4()) == (
        T.CAPACITY_FULL
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shown": False, "capacity": 100, "used": 1},
        {"shown": True, "capacity": 0, "used": 1},
        {"shown": True, "capacity": 100, "used": 1, "bound": False},
    ],
)
async def test_nothing_is_shown_when_off_unlimited_or_unbound(kwargs: dict[str, Any]) -> None:
    assert await capacity_line(scope(**kwargs), uuid.uuid4()) == ""
