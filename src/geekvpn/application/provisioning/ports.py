"""Ports for the order and provisioning context.

These are the seams the provisioning services are written against. The
repositories are asynchronous because provisioning talks to a remote panel in
the same unit of work, and blocking a worker thread on an HTTP call to somebody
else's Marzban instance is how one slow node stalls every other order.

The one exception is :class:`SyncOrderRepository`. Payment approval runs in the
synchronous scope (``infrastructure/di/sync_scope.py``), and the order must move
to PAID inside that same transaction - otherwise money is captured and the
order still says PENDING, which is exactly the paid-but-serviceless state the
whole design exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.application.ports.panel import PanelAdapter
from geekvpn.domain.panels.enums import PanelKind
from geekvpn.domain.provisioning.enums import NodeState, SubscriptionState
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeRecord:
    """A sellable panel instance, as the selector needs to see it.

    Deliberately not the SQLAlchemy model and not a domain entity: node
    selection is a pure function over a handful of numbers, and giving it a
    plain record keeps it testable without a database and without dragging the
    panel credentials through the decision.
    """

    id: str
    name_fa: str
    panel_kind: PanelKind
    state: NodeState
    accepting_new: bool
    #: ``0`` means "no declared ceiling", not "full".
    capacity: int
    account_count: int
    country_code: str | None = None
    sort_order: int = 0

    @property
    def has_room(self) -> bool:
        """True when one more account fits."""
        return self.capacity == 0 or self.account_count < self.capacity

    @property
    def load_ratio(self) -> float:
        """0.0 for an uncapped node, so uncapped nodes are preferred last-resort
        equals rather than always-winners."""
        if self.capacity == 0:
            return 0.0
        return self.account_count / self.capacity


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeAdminRecord:
    """A node as the admin panel is allowed to see it.

    Separate from :class:`NodeRecord` because an operator needs the connection
    settings that selection has no business seeing. It still carries
    ``has_password`` rather than the password: an operator editing a node needs
    to know whether one is set, never what it is, and a field that is never
    populated cannot be leaked by a careless serialiser.
    """

    id: str
    name_fa: str
    panel_kind: PanelKind
    state: NodeState
    base_url: str
    username: str
    has_password: bool
    verify_tls: bool
    timeout_seconds: float
    capacity: int
    account_count: int
    accepting_new: bool
    country_code: str | None = None
    sort_order: int = 0
    last_check_at: datetime | None = None
    last_error: str | None = None


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> str: ...


@runtime_checkable
class OrderNumberGenerator(Protocol):
    """Produces the human-quotable order number.

    Separate from :class:`IdGenerator` because the number is shown to customers
    and quoted to support, so it is short, sequential and Jalali-year scoped,
    while the id is an opaque primary key.
    """

    def next_number(self, *, jalali_year: int) -> str: ...


@runtime_checkable
class EventPublisher(Protocol):
    def publish_all(self, events: Sequence[object]) -> None: ...


@runtime_checkable
class OrderRepository(Protocol):
    async def get(self, order_id: str) -> Order | None: ...

    async def get_by_number(self, number: str) -> Order | None: ...

    async def get_by_invoice(self, invoice_id: str) -> Order | None: ...

    async def list_stuck(self, *, older_than: datetime, limit: int = 50) -> Sequence[Order]: ...

    async def add(self, order: Order) -> None: ...

    async def update(self, order: Order) -> None: ...


@runtime_checkable
class SyncOrderRepository(Protocol):
    """The payment-scope view of the same table. Read the module docstring."""

    def get_by_invoice(self, invoice_id: str) -> Order | None: ...

    def update(self, order: Order) -> None: ...


@runtime_checkable
class SubscriptionRepository(Protocol):
    async def get(self, subscription_id: str) -> Subscription | None: ...

    async def get_by_order(self, order_id: str) -> Subscription | None: ...

    async def add(self, subscription: Subscription) -> None: ...

    async def update(self, subscription: Subscription) -> None: ...

    async def search(
        self,
        *,
        state: SubscriptionState | None = None,
        user_id: int | None = None,
        node_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Subscription], int]:
        """A filtered page plus the unpaged total.

        Used by the admin list and by the usage sync, which needs every account
        on one node so it can ask the panel for them in a single request.
        """
        ...


@runtime_checkable
class NodeRepository(Protocol):
    async def get(self, node_id: str) -> NodeRecord | None: ...

    async def list_sellable(self) -> Sequence[NodeRecord]:
        """Every node that could conceivably take a new account.

        Returns candidates, not a decision. Filtering lives in the selector so
        that "why did this order land on Frankfurt" is answerable by reading one
        pure function instead of a SQL WHERE clause.
        """
        ...


@runtime_checkable
class PanelProvider(Protocol):
    """Builds a live adapter for a node.

    Exists so the provisioning service never sees credentials, a factory, or a
    registry - only "give me something that speaks :class:`PanelAdapter`".
    """

    async def for_node(self, node: NodeRecord) -> PanelAdapter: ...


__all__ = [
    "EventPublisher",
    "IdGenerator",
    "NodeAdminRecord",
    "NodeRecord",
    "NodeRepository",
    "OrderNumberGenerator",
    "OrderRepository",
    "PanelProvider",
    "SubscriptionRepository",
    "SyncOrderRepository",
]
