"""An owner, a friend and one service, behind the real `BotServiceOwnership`.

Shared by the adapter's unit tests and the Mini App endpoint tests, so the
endpoints are exercised through the same rules the bot uses rather than a
stand-in that could agree with whatever the router expects.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from geekvpn.application.platform.settings_service import REFUND_WINDOW_HOURS
from geekvpn.application.provisioning.unused_refund import UnusedRefund
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.identity.user import User
from geekvpn.domain.provisioning import Subscription
from geekvpn.domain.provisioning.enums import OrderSource
from geekvpn.domain.provisioning.order import Order
from geekvpn.infrastructure.bot.ownership import BotServiceOwnership
from tests.unit.provisioning.fakes import FrozenClock, InMemoryOrders, InMemorySubscriptions

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
OWNER_TG = 1001
FRIEND_TG = 2002


class _Subscriptions(InMemorySubscriptions):
    async def list_for_user(self, user_id: int) -> Sequence[Subscription]:
        return [s for s in self.rows.values() if s.user_id == user_id]


class _Users:
    def __init__(self, *users: User) -> None:
        self.items = {user.id: user for user in users}

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self.items.get(user_id)

    async def get_by_telegram_id(self, telegram_id: int, *, reseller_id: Any = None) -> User | None:
        return next((u for u in self.items.values() if u.telegram_id == telegram_id), None)


class _Settings:
    def __init__(self, **values: Any) -> None:
        self.values = values

    async def get(self, definition: Any) -> Any:
        return self.values.get(definition.key, definition.default)


class _Session:
    commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _SyncScope:
    """What the adapter's bridge work touches: the engine and the reports."""

    def __init__(self) -> None:
        self.dispatched: list[int] = []
        self.reports: list[str] = []
        outer = self

        class engine:
            @staticmethod
            def dispatch(*, user_id: int, message: Any, source: str) -> None:
                outer.dispatched.append(user_id)

        class operator_reports:
            @staticmethod
            def send(kind: Any, text: str) -> None:
                outer.reports.append(text)

        self.engine = engine
        self.operator_reports = operator_reports


class _Bridge:
    def __init__(self, scope: _SyncScope) -> None:
        self.scope = scope

    async def run(self, work: Callable[[Any], Any]) -> Any:
        return work(self.scope)


class World:
    def __init__(self, *, settings: dict[str, Any] | None = None) -> None:
        self.owner = User.register(user_id=uuid.uuid4(), telegram_id=OWNER_TG, referral_code="A")
        self.friend = User.register(user_id=uuid.uuid4(), telegram_id=FRIEND_TG, referral_code="B")
        self.subscriptions = _Subscriptions()
        self.order = Order.place(
            uuid.uuid4().hex,
            number="1405-00042",
            user_id=OWNER_TG,
            plan_id=str(uuid.uuid4()),
            plan_name_fa="ماهانه",
            duration_days=30,
            list_price=Money(200_000),
            total=Money(200_000),
            source=OrderSource.BOT,
            now=NOW - timedelta(hours=1),
        )
        self.sub_id = uuid.uuid4()
        self.sync = _SyncScope()
        self.refunds = UnusedRefund(
            subscriptions=self.subscriptions,
            orders=InMemoryOrders(self.order),
            refresh_usage=self._no_refresh,
            revoke=self._revoke,
            credit=self._credit,
            window=self._window,
            clock=FrozenClock(NOW),
        )
        self.settings = settings or {}
        self.ownership = BotServiceOwnership(
            users=_Users(self.owner, self.friend),  # type: ignore[arg-type]
            subscriptions=self.subscriptions,  # type: ignore[arg-type]
            orders=InMemoryOrders(self.order),  # type: ignore[arg-type]
            session=_Session(),  # type: ignore[arg-type]
            settings=_Settings(**self.settings),  # type: ignore[arg-type]
            bridge=_Bridge(self.sync),  # type: ignore[arg-type]
            reseller_id=None,
            refunds=self.refunds,
        )

    async def _no_refresh(self, subscription_id: str) -> Subscription | None:
        return None

    async def _revoke(self, subscription_id: str, reason_fa: str) -> Subscription:
        sub = await self.subscriptions.get(subscription_id)
        assert sub is not None
        sub.revoke(reason_fa=reason_fa, at=NOW)
        return sub

    async def _credit(self, user_id: int, amount: Money, number: str) -> None:
        return None

    async def _window(self) -> int:
        return int(self.settings.get(REFUND_WINDOW_HOURS.key, 0))

    async def service(self) -> Subscription:
        sub = Subscription.activate(
            self.sub_id.hex,
            user_id=OWNER_TG,
            order_id=self.order.id,
            plan_id=self.order.plan_id,
            remote_username="gv_1001_x",
            now=NOW - timedelta(hours=1),
            duration_days=30,
        )
        self.order.mark_paid(at=NOW - timedelta(hours=1))
        self.order.start_provisioning()
        self.order.mark_active(subscription_id=sub.id, at=NOW - timedelta(hours=1))
        await self.subscriptions.add(sub)
        return sub
