"""The bot's ports must have implementations that actually satisfy them.

`application/bot/ports.py` declared eight Protocols and nothing implemented
them, so `BotServices` could never be assembled and every handler was handed
`None`. A structural check is the cheapest guard against that recurring: these
Protocols are `runtime_checkable`, so conformance is assertable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geekvpn.application.bot import ports
from geekvpn.application.bot.read_models import ServerHealth
from geekvpn.application.bot.read_models import SubscriptionState as CardState
from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.domain.identity.enums import Language, UserStatus
from geekvpn.domain.identity.user import User
from geekvpn.domain.panels.enums import PanelKind
from geekvpn.domain.provisioning.enums import NodeState, SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.bot.readers import (
    SqlProfileReader,
    SqlServerStatusReader,
    SqlSubscriptionCardReader,
)

NOW = datetime(2026, 8, 7, tzinfo=UTC)
USER_ID = uuid.uuid4()
SUB_ID = str(uuid.uuid4())
PLAN_ID = str(uuid.uuid4())


def make_user() -> User:
    return User(
        USER_ID,
        telegram_id=555,
        referral_code="ref-1",
        username="hasti",
        first_name="هستی",
        last_name=None,
        language=Language.FA,
        status=UserStatus.ACTIVE,
        created_at=NOW,
    )


class FakeUsers:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.updated: list[User] = []

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self.user if self.user and self.user.id == user_id else None

    async def update(self, user: User) -> None:
        self.updated.append(user)


class FakeSubscriptions:
    def __init__(self, subs: list[Subscription]) -> None:
        self.subs = subs

    async def list_for_user(self, telegram_id: int, *, active_only: bool = False):
        return self.subs


class FakeOrders:
    def __init__(self, plan_name: str = "پلن طلایی") -> None:
        self.plan_name = plan_name

    async def get(self, order_id: str):
        class _Order:
            plan_name_fa = self.plan_name

        return _Order()

    async def count_for_user(self, telegram_id: int) -> int:
        return 3


class FakeNodes:
    def __init__(self, nodes: list[NodeRecord]) -> None:
        self.nodes = nodes

    async def list_sellable(self):
        return self.nodes


def make_subscription(*, quota_mib: int | None, used_mib: int) -> Subscription:
    return Subscription(
        SUB_ID,
        user_id=555,
        order_id="ord-1",
        plan_id=PLAN_ID,
        state=SubscriptionState.ACTIVE,
        node_id="fra",
        remote_username="u1",
        started_at=NOW,
        expires_at=datetime(2026, 12, 1, tzinfo=UTC),
        traffic_limit_mib=quota_mib,
        traffic_used_mib=used_mib,
        device_limit=2,
    )


# -- the check that was never made ----------------------------------------


def test_the_readers_satisfy_the_ports_they_are_written_for() -> None:
    subscriptions = SqlSubscriptionCardReader(
        users=FakeUsers(None),  # type: ignore[arg-type]
        subscriptions=FakeSubscriptions([]),  # type: ignore[arg-type]
        orders=FakeOrders(),  # type: ignore[arg-type]
    )
    profiles = SqlProfileReader(
        users=FakeUsers(None),  # type: ignore[arg-type]
        orders=FakeOrders(),  # type: ignore[arg-type]
    )
    servers = SqlServerStatusReader(nodes=FakeNodes([]))  # type: ignore[arg-type]

    assert isinstance(subscriptions, ports.SubscriptionReader)
    assert isinstance(profiles, ports.ProfileReader)
    assert isinstance(servers, ports.ServerStatusReader)


# -- subscriptions ---------------------------------------------------------


async def test_traffic_is_reported_in_the_gibibytes_the_customer_was_sold() -> None:
    reader = SqlSubscriptionCardReader(
        users=FakeUsers(make_user()),  # type: ignore[arg-type]
        subscriptions=FakeSubscriptions(  # type: ignore[arg-type]
            [make_subscription(quota_mib=50 * 1024, used_mib=10 * 1024)]
        ),
        orders=FakeOrders(),  # type: ignore[arg-type]
    )

    [card] = await reader.list_for_user(USER_ID)

    assert card.quota_gib == 50
    assert card.used_gib == 10.0
    assert card.usage_fraction == 0.2


async def test_an_unlimited_plan_has_no_quota_and_draws_no_bar() -> None:
    reader = SqlSubscriptionCardReader(
        users=FakeUsers(make_user()),  # type: ignore[arg-type]
        subscriptions=FakeSubscriptions(  # type: ignore[arg-type]
            [make_subscription(quota_mib=None, used_mib=999)]
        ),
        orders=FakeOrders(),  # type: ignore[arg-type]
    )

    [card] = await reader.list_for_user(USER_ID)

    assert card.is_unlimited
    assert card.usage_fraction == 0.0


async def test_an_unknown_user_gets_an_empty_list_not_an_error() -> None:
    reader = SqlSubscriptionCardReader(
        users=FakeUsers(None),  # type: ignore[arg-type]
        subscriptions=FakeSubscriptions([]),  # type: ignore[arg-type]
        orders=FakeOrders(),  # type: ignore[arg-type]
    )

    assert await reader.list_for_user(uuid.uuid4()) == []


async def test_the_plan_name_comes_from_the_order_that_created_it() -> None:
    reader = SqlSubscriptionCardReader(
        users=FakeUsers(make_user()),  # type: ignore[arg-type]
        subscriptions=FakeSubscriptions(  # type: ignore[arg-type]
            [make_subscription(quota_mib=1024, used_mib=0)]
        ),
        orders=FakeOrders(plan_name="پلن نقره‌ای"),  # type: ignore[arg-type]
    )

    [card] = await reader.list_for_user(USER_ID)

    assert card.plan_name_fa == "پلن نقره‌ای"
    assert card.state is CardState.ACTIVE


# -- server status ---------------------------------------------------------


def node(node_id: str, *, state: NodeState, capacity: int, used: int) -> NodeRecord:
    return NodeRecord(
        id=node_id,
        name_fa="فرانکفورت",
        panel_kind=PanelKind.MARZBAN,
        state=state,
        accepting_new=True,
        capacity=capacity,
        account_count=used,
    )


async def test_an_uncapped_node_reports_no_load_percentage() -> None:
    """A percentage of an unbounded capacity is not a number."""
    reader = SqlServerStatusReader(
        nodes=FakeNodes([node("a", state=NodeState.ONLINE, capacity=0, used=900)])  # type: ignore[arg-type]
    )

    [row] = await reader.rows()

    assert row.load_percent is None
    assert row.health is ServerHealth.HEALTHY


async def test_load_is_capped_at_a_hundred_percent() -> None:
    reader = SqlServerStatusReader(
        nodes=FakeNodes([node("a", state=NodeState.ONLINE, capacity=10, used=25)])  # type: ignore[arg-type]
    )

    [row] = await reader.rows()

    assert row.load_percent == 100


async def test_a_retired_node_reads_as_down_not_as_unknown() -> None:
    reader = SqlServerStatusReader(
        nodes=FakeNodes([node("a", state=NodeState.RETIRED, capacity=10, used=1)])  # type: ignore[arg-type]
    )

    [row] = await reader.rows()

    assert row.health is ServerHealth.DOWN


# -- profile ---------------------------------------------------------------


async def test_the_profile_carries_the_order_count() -> None:
    reader = SqlProfileReader(
        users=FakeUsers(make_user()),  # type: ignore[arg-type]
        orders=FakeOrders(),  # type: ignore[arg-type]
    )

    summary = await reader.summary(USER_ID)

    assert summary.telegram_id == 555
    assert summary.order_count == 3


async def test_setting_a_display_name_keeps_the_username() -> None:
    """`refresh_profile` treats every argument as authoritative, so a field the
    caller does not mean to change has to be passed through explicitly."""
    users = FakeUsers(make_user())
    reader = SqlProfileReader(users=users, orders=FakeOrders())  # type: ignore[arg-type]

    await reader.set_display_name(USER_ID, "کاربر تازه")

    assert users.updated[0].username == "hasti"
    assert users.updated[0].display_name == "کاربر تازه"
