"""In-memory doubles for the provisioning context.

Structural, not inherited: every one of these satisfies its ``Protocol`` by
shape, which is the whole reason the ports are Protocols.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import count

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.domain.panels.enums import AccountState, PanelKind
from geekvpn.domain.panels.errors import PanelError, PanelUnreachable
from geekvpn.domain.panels.values import (
    AccountSpec,
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
)
from geekvpn.domain.provisioning.enums import NodeState
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "geekvpn:test")


class FrozenClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class SequentialIds:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._counter = count(1)

    def new_id(self) -> str:
        return f"{self._prefix}-{next(self._counter):04d}"


class SequentialNumbers:
    def __init__(self) -> None:
        self._counter = count(1)

    async def next_number(self, *, jalali_year: int) -> str:
        return f"{jalali_year}-{next(self._counter):04d}"


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish_all(self, events: Sequence[object]) -> None:
        self.events.extend(events)

    def names(self) -> list[str]:
        return [type(event).__name__ for event in self.events]


class InMemoryOrders:
    """Serves both the async and the sync order port."""

    def __init__(self, *orders: Order) -> None:
        self.rows: dict[str, Order] = {order.id: order for order in orders}

    # async port
    async def get_for_update(self, order_id: str) -> Order | None:
        """No locking to simulate; in-memory access is already serialised.

        Present because the port declares it, and a fake that is a weaker
        contract than the real repository is how the double-provision went
        unnoticed in the first place.
        """
        return await self.get(order_id)

    async def get(self, order_id: str) -> Order | None:
        return self.rows.get(order_id)

    async def get_by_number(self, number: str) -> Order | None:
        return next((o for o in self.rows.values() if o.number == number), None)

    async def get_by_invoice(self, invoice_id: str) -> Order | None:
        return next((o for o in self.rows.values() if o.invoice_id == invoice_id), None)

    async def list_stuck(self, *, older_than: datetime, limit: int = 50) -> Sequence[Order]:
        return [o for o in self.rows.values() if o.paid_at is not None and o.paid_at <= older_than][
            :limit
        ]

    async def add(self, order: Order) -> None:
        self.rows[order.id] = order

    async def update(self, order: Order) -> None:
        self.rows[order.id] = order


class SyncOrders:
    def __init__(self, *orders: Order) -> None:
        self.rows: dict[str, Order] = {order.id: order for order in orders}
        self.by_invoice: dict[str, str] = {}

    def link(self, invoice_id: str, order_id: str) -> None:
        self.by_invoice[invoice_id] = order_id

    def get_by_invoice(self, invoice_id: str) -> Order | None:
        order_id = self.by_invoice.get(invoice_id)
        return self.rows.get(order_id) if order_id else None

    def update(self, order: Order) -> None:
        self.rows[order.id] = order


class InMemorySubscriptions:
    def __init__(self) -> None:
        self.rows: dict[str, Subscription] = {}

    async def get(self, subscription_id: str) -> Subscription | None:
        return self.rows.get(subscription_id)

    async def get_by_order(self, order_id: str) -> Subscription | None:
        return next((s for s in self.rows.values() if s.order_id == order_id), None)

    async def add(self, subscription: Subscription) -> None:
        self.rows[subscription.id] = subscription

    async def update(self, subscription: Subscription) -> None:
        self.rows[subscription.id] = subscription


class InMemoryNodes:
    def __init__(self, *nodes: NodeRecord) -> None:
        self.rows = {node.id: node for node in nodes}

    async def get(self, node_id: str) -> NodeRecord | None:
        return self.rows.get(node_id)

    async def list_sellable(self) -> Sequence[NodeRecord]:
        return tuple(self.rows.values())


class FakePanel:
    """A panel that records what it was asked to do."""

    kind = PanelKind.MARZBAN
    capabilities = frozenset()

    def __init__(self, *, fail_with: PanelError | None = None) -> None:
        self.created: list[AccountSpec] = []
        self.renewed: list[PanelAccountRef] = []
        self.idempotency_keys: list[str] = []
        self._fail_with = fail_with

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        if self._fail_with is not None:
            raise self._fail_with
        self.created.append(spec)
        self.idempotency_keys.append(idempotency_key)
        return PanelAccount(
            ref=PanelAccountRef(panel_id=_NAMESPACE, username=spec.username, external_id="ext-1"),
            state=AccountState.ACTIVE,
            usage=AccountUsage(used_bytes=0, measured_at=datetime(2026, 8, 5, tzinfo=UTC)),
            expires_at=spec.expires_at,
            subscription_url=f"https://panel.example.com/sub/{spec.username}",
        )

    async def renew(self, ref: PanelAccountRef, **kwargs: object) -> PanelAccount:
        if self._fail_with is not None:
            raise self._fail_with
        self.renewed.append(ref)
        return PanelAccount(
            ref=ref,
            state=AccountState.ACTIVE,
            usage=AccountUsage(used_bytes=0, measured_at=datetime(2026, 8, 5, tzinfo=UTC)),
        )


class FakePanelProvider:
    def __init__(self, panel: FakePanel) -> None:
        self.panel = panel
        self.requested: list[str] = []

    async def for_node(self, node: NodeRecord) -> FakePanel:
        self.requested.append(node.id)
        return self.panel


UNREACHABLE = PanelUnreachable("connection refused")


def node(
    node_id: str,
    *,
    capacity: int = 100,
    account_count: int = 0,
    state: NodeState = NodeState.ONLINE,
    accepting_new: bool = True,
    country_code: str | None = "DE",
    sort_order: int = 0,
) -> NodeRecord:
    return NodeRecord(
        id=node_id,
        name_fa="آلمان",
        panel_kind=PanelKind.MARZBAN,
        state=state,
        accepting_new=accepting_new,
        capacity=capacity,
        account_count=account_count,
        country_code=country_code,
        sort_order=sort_order,
    )
