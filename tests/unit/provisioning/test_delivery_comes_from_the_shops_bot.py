"""A reseller's customer is handed their link by the reseller's own bot.

The delivery notice crossed into the synchronous side with no shop, so it was
always built on our bot's token. A reseller's customer has only ever spoken to
the reseller's bot, and Telegram refuses a bot that a person never started: the
account was created, "my services" showed it, and the message carrying the link
never arrived.

The scope a provision runs in does not reliably know the shop either. The
worker that delivers every card and gateway payment builds a plain scope, and
so does an operator's retry from the admin panel. The order does know, so the
shop is read from the order.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from geekvpn.domain.provisioning.events import SubscriptionActivated
from geekvpn.infrastructure.di import scope as scope_module
from geekvpn.infrastructure.di.scope import RequestScope

pytestmark = pytest.mark.unit

SHOP = uuid.uuid4()


class _Subscription:
    order_id = "order-1"


class _Subscriptions:
    async def get(self, subscription_id: str) -> Any:
        return _Subscription() if subscription_id == "sub-1" else None


class _Orders:
    def __init__(self, shop: uuid.UUID | None) -> None:
        self._shop = shop

    async def shop_of(self, order_id: str) -> uuid.UUID | None:
        return self._shop if order_id == "order-1" else None


class _Session:
    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None: ...


class _Container:
    def sync_sessions(self) -> _Session:
        return _Session()


class _Delivery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    def on_subscription_activated(self, event: Any, link: str | None) -> None:
        self.sent.append((event.subscription_id, link))


class _SyncScope:
    def __init__(self, delivery: _Delivery) -> None:
        self.delivery_notifications = delivery


def _scope(*, shop_of_order: uuid.UUID | None, reseller: Any = None) -> RequestScope:
    scope = RequestScope(container=_Container(), session=None, reseller=reseller)  # type: ignore[arg-type]
    # Cached properties live in the instance dict, so these stand in for the
    # repositories without touching a database.
    scope.__dict__["subscriptions"] = _Subscriptions()
    scope.__dict__["orders"] = _Orders(shop_of_order)
    return scope


def _event() -> SubscriptionActivated:
    return SubscriptionActivated(
        subscription_id="sub-1", user_id=42, plan_id="plan-1", expires_at="2026-12-01"
    )


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID | None]:
    """The shop each synchronous scope was built for, and nothing else."""
    shops: list[uuid.UUID | None] = []
    delivery = _Delivery()

    def build(container: Any, session: Any, *, reseller_id: uuid.UUID | None = None) -> Any:
        shops.append(reseller_id)
        return _SyncScope(delivery)

    async def inline(fn: Any) -> Any:
        return fn()

    monkeypatch.setattr(scope_module, "build_sync_scope", build)
    monkeypatch.setattr(scope_module, "run_in_threadpool", inline)
    return shops


async def test_a_resellers_order_is_announced_from_the_resellers_bot(
    built: list[uuid.UUID | None],
) -> None:
    # The worker's scope: no shop of its own, delivering a reseller's order.
    await _scope(shop_of_order=SHOP)._announce_delivery(_event(), "https://x/sub/t")

    assert built == [SHOP]


async def test_our_own_order_is_announced_from_our_bot(
    built: list[uuid.UUID | None],
) -> None:
    await _scope(shop_of_order=None)._announce_delivery(_event(), "https://x/sub/t")

    assert built == [None]


async def test_the_request_shop_is_used_when_the_scope_has_one(
    built: list[uuid.UUID | None],
) -> None:
    class _Reseller:
        id = SHOP

    await _scope(shop_of_order=None, reseller=_Reseller())._announce_delivery(
        _event(), "https://x/sub/t"
    )

    assert built == [SHOP]
