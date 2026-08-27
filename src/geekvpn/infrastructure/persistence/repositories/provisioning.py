"""Order and subscription repositories.

The queries here are the ones the whole business runs on: "what did this
customer buy", "whose service dies this week", "what is stuck half-provisioned".
Each is filtered in SQL. The expiring-soon query in particular runs on a timer
over every live subscription, and doing it in Python would mean loading the
entire table every few minutes.

No method commits. The unit of work owns the transaction, so an order and the
subscription it produced either both land or neither does - which is the whole
reason a customer never ends up paid-but-serviceless.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.provisioning.enums import OrderState, SubscriptionState
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.persistence.mappers.provisioning import (
    order_apply,
    order_to_domain,
    order_to_row,
    subscription_apply,
    subscription_to_domain,
    subscription_to_row,
)
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)

#: States whose rows the provisioning worker is allowed to pick up.
#:
#: PROVISIONING is included because `start_provisioning` commits before the
#: panel call. A worker killed between the two leaves an order in that state
#: forever: paid for, no service, and invisible to the only thing that could
#: have recovered it. The grace period is what keeps the sweep from racing a
#: provision that is merely still in flight.
_RETRYABLE = (
    OrderState.PAID.value,
    OrderState.FAILED.value,
    OrderState.PROVISIONING.value,
)


class SqlAlchemyOrderRepository:
    def __init__(
        self, session: AsyncSession, *, reseller_id: uuid.UUID | None = None
    ) -> None:
        self._session = session
        self._reseller_id = reseller_id

    def _shop(self, column: Any) -> Any:
        """`WHERE reseller_id = ...`, or `IS NULL` for the platform's own shop.

        `None` is a real answer rather than "any shop": the platform's rows are
        the ones with no reseller, and matching everything would put a
        reseller's customers back in front of our own bot.
        """
        return (
            column.is_(None) if self._reseller_id is None else column == self._reseller_id
        )


    async def get(self, order_id: str) -> Order | None:
        row = await self._session.get(OrderModel, order_id)
        return order_to_domain(row) if row else None

    async def get_for_update(self, order_id: str) -> Order | None:
        """Load an order and hold its row until the transaction ends.

        `provision` checks for an existing subscription and inserts one if
        there is none. Two callers doing that concurrently - the retry sweep
        and an operator's retry-provision button - both see none and both
        insert. uq_subscriptions_order makes the second fail; this makes it
        wait instead, so the second caller sees the first one's result.
        """
        stmt = select(OrderModel).where(OrderModel.id == order_id).with_for_update()
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return order_to_domain(row) if row else None

    async def get_by_number(self, number: str) -> Order | None:
        stmt = select(OrderModel).where(OrderModel.number == number)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return order_to_domain(row) if row else None

    async def get_by_invoice(self, invoice_id: str) -> Order | None:
        stmt = select(OrderModel).where(OrderModel.invoice_id == invoice_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return order_to_domain(row) if row else None

    async def list_for_user(
        self, user_id: int, *, limit: int = 20, offset: int = 0
    ) -> Sequence[Order]:
        stmt = (
            select(OrderModel)
            .where(OrderModel.user_id == user_id, self._shop(OrderModel.reseller_id))
            .order_by(OrderModel.placed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [order_to_domain(row) for row in rows]

    async def count_for_user(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(OrderModel)
            .where(OrderModel.user_id == user_id, self._shop(OrderModel.reseller_id))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def search(
        self,
        *,
        state: OrderState | None = None,
        user_id: int | None = None,
        number: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Order], int]:
        """Platform-wide order list for the admin panel, with the total.

        Returns the count alongside the page because the operator screen needs
        to paginate, and running the filter twice from the router would let the
        two drift apart.
        """
        filters = []
        if state is not None:
            filters.append(OrderModel.state == state.value)
        if user_id is not None:
            filters.append(OrderModel.user_id == user_id)
        if number is not None:
            filters.append(OrderModel.number == number)

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(OrderModel).where(*filters)
                )
            ).scalar_one()
        )
        stmt = (
            select(OrderModel)
            .where(*filters)
            .order_by(OrderModel.placed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [order_to_domain(row) for row in rows], total

    async def has_completed_order(self, user_id: int) -> bool:
        """Used for first-purchase pricing and referral conversion.

        Cancelled and failed orders deliberately do not count: a customer whose
        only order failed has still never successfully bought anything, and
        charging them the returning-customer price would be indefensible.
        """
        stmt = (
            select(OrderModel.id)
            .where(
                OrderModel.user_id == user_id,
                # Scoped: "have they bought before" is a question about this
                # shop. A customer's first purchase from a reseller is a first
                # purchase, whatever they have bought from us.
                self._shop(OrderModel.reseller_id),
                OrderModel.state.in_((OrderState.ACTIVE.value, OrderState.REFUNDED.value)),
            )
            .limit(1)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def list_stuck(self, *, older_than: datetime, limit: int = 50) -> Sequence[Order]:
        """Paid or failed and still without a service. The retry queue."""
        stmt = (
            select(OrderModel)
            .where(
                OrderModel.state.in_(_RETRYABLE),
                OrderModel.paid_at.is_not(None),
                OrderModel.paid_at <= older_than,
            )
            .order_by(OrderModel.paid_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [order_to_domain(row) for row in rows]

    async def add(self, order: Order) -> None:
        row = order_to_row(order)
        # Stamped on insert. A row written without it belongs to the
        # platform's shop by definition, which is the wrong answer for every
        # reseller's customer - and invisible from both sides afterwards.
        row.reseller_id = self._reseller_id
        self._session.add(row)
        await self._session.flush()

    async def update(self, order: Order) -> None:
        row = await self._session.get(OrderModel, order.id)
        if row is None:
            raise NotFoundError("Order not found.", order_id=order.id)
        order_apply(row, order)
        await self._session.flush()


class SqlAlchemySubscriptionRepository:
    def __init__(
        self, session: AsyncSession, *, reseller_id: uuid.UUID | None = None
    ) -> None:
        self._session = session
        self._reseller_id = reseller_id

    def _shop(self, column: Any) -> Any:
        """`WHERE reseller_id = ...`, or `IS NULL` for the platform's own shop.

        `None` is a real answer rather than "any shop": the platform's rows are
        the ones with no reseller, and matching everything would put a
        reseller's customers back in front of our own bot.
        """
        return (
            column.is_(None) if self._reseller_id is None else column == self._reseller_id
        )


    async def get(self, subscription_id: str) -> Subscription | None:
        row = await self._session.get(SubscriptionModel, subscription_id)
        return subscription_to_domain(row) if row else None

    async def get_by_order(self, order_id: str) -> Subscription | None:
        stmt = select(SubscriptionModel).where(SubscriptionModel.order_id == order_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return subscription_to_domain(row) if row else None

    async def get_by_remote_username(self, username: str) -> Subscription | None:
        stmt = select(SubscriptionModel).where(SubscriptionModel.remote_username == username)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return subscription_to_domain(row) if row else None

    async def list_for_user(
        self, user_id: int, *, active_only: bool = False
    ) -> Sequence[Subscription]:
        stmt: Select[Any] = select(SubscriptionModel).where(
            SubscriptionModel.user_id == user_id,
            self._shop(SubscriptionModel.reseller_id),
        )
        if active_only:
            stmt = stmt.where(SubscriptionModel.state == SubscriptionState.ACTIVE.value)
        stmt = stmt.order_by(SubscriptionModel.expires_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_domain(row) for row in rows]

    async def list_for_reseller(
        self, reseller_id: uuid.UUID
    ) -> Sequence[Subscription]:
        """Everything one reseller has sold.

        Read whole rather than filtered by state: arrears enforcement needs
        both the active ones to suspend and the suspended ones to bring back,
        and asking twice is two queries for one decision.
        """
        stmt = (
            select(SubscriptionModel)
            .where(SubscriptionModel.reseller_id == reseller_id)
            .order_by(SubscriptionModel.expires_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_domain(row) for row in rows]

    async def search(
        self,
        *,
        state: SubscriptionState | None = None,
        user_id: int | None = None,
        node_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Subscription], int]:
        """Platform-wide subscription list for the admin panel, with the total."""
        filters = []
        if state is not None:
            filters.append(SubscriptionModel.state == state.value)
        if user_id is not None:
            filters.append(SubscriptionModel.user_id == user_id)
        if node_id is not None:
            filters.append(SubscriptionModel.node_id == node_id)

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(SubscriptionModel).where(*filters)
                )
            ).scalar_one()
        )
        stmt = (
            select(SubscriptionModel)
            .where(*filters)
            .order_by(SubscriptionModel.expires_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_domain(row) for row in rows], total

    async def list_expiring(
        self, *, now: datetime, within_days: int, limit: int = 500
    ) -> Sequence[Subscription]:
        """Active subscriptions whose expiry falls inside the window.

        Already-expired rows are excluded: they need the expiry sweep, not a
        reminder, and telling someone their service ends in -2 days is the kind
        of message that costs a renewal.
        """
        horizon = now + timedelta(days=within_days)
        stmt = (
            select(SubscriptionModel)
            .where(
                SubscriptionModel.state == SubscriptionState.ACTIVE.value,
                SubscriptionModel.expires_at > now,
                SubscriptionModel.expires_at <= horizon,
            )
            .order_by(SubscriptionModel.expires_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_domain(row) for row in rows]

    async def list_lapsed(self, *, now: datetime, limit: int = 500) -> Sequence[Subscription]:
        """Still marked active but past their date. The expiry sweep's input."""
        stmt = (
            select(SubscriptionModel)
            .where(
                SubscriptionModel.state == SubscriptionState.ACTIVE.value,
                SubscriptionModel.expires_at <= now,
            )
            .order_by(SubscriptionModel.expires_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_domain(row) for row in rows]

    async def list_for_sync(
        self, *, stale_before: datetime, limit: int = 200
    ) -> Sequence[Subscription]:
        """Usable subscriptions whose usage figures are old.

        Rows never synced (NULL ``last_synced_at``) sort first, because a brand
        new account with no reading is the one most likely to have failed
        silently on the panel.
        """
        stmt = (
            select(SubscriptionModel)
            .where(
                SubscriptionModel.state.in_(
                    (
                        SubscriptionState.ACTIVE.value,
                        SubscriptionState.EXHAUSTED.value,
                    )
                ),
                (SubscriptionModel.last_synced_at.is_(None))
                | (SubscriptionModel.last_synced_at <= stale_before),
            )
            .order_by(
                SubscriptionModel.last_synced_at.is_not(None),
                SubscriptionModel.last_synced_at,
            )
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [subscription_to_domain(row) for row in rows]

    async def count_active_on_node(self, node_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(SubscriptionModel)
            .where(
                SubscriptionModel.node_id == node_id,
                SubscriptionModel.state == SubscriptionState.ACTIVE.value,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add(self, subscription: Subscription) -> None:
        row = subscription_to_row(subscription)
        # Only when the caller has not already said. A reseller's *sale* sets
        # this explicitly - it is the seller, not merely the shop - and the
        # scope's answer must not overwrite a more specific one.
        if row.reseller_id is None:
            row.reseller_id = self._reseller_id
        self._session.add(row)
        await self._session.flush()

    async def update(self, subscription: Subscription) -> None:
        row = await self._session.get(SubscriptionModel, subscription.id)
        if row is None:
            raise NotFoundError("Subscription not found.", subscription_id=subscription.id)
        subscription_apply(row, subscription)
        await self._session.flush()


__all__ = ["SqlAlchemyOrderRepository", "SqlAlchemySubscriptionRepository"]


class JalaliOrderNumbers:
    """``application.provisioning.ports.OrderNumberGenerator``.

    Same reasoning as invoice numbering: a count of the numbers already carrying
    this Jalali year, not a Postgres sequence, because order numbers restart
    each year and a sequence has no idea when Nowruz is.

    The count is racy under concurrency and the unique constraint on
    ``orders.number`` is what actually enforces uniqueness - a collision surfaces
    as an integrity error on insert, which the caller retries. That is the right
    trade here: the alternative is a table lock on the hottest write path in the
    system to protect a number that only humans read.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_number(self, *, jalali_year: int) -> str:
        stmt = (
            select(func.count())
            .select_from(OrderModel)
            .where(OrderModel.number.like(f"{jalali_year}-%"))
        )
        used = int((await self._session.execute(stmt)).scalar_one())
        return f"{jalali_year}-{used + 1:05d}"


class SyncOrderRepository:
    """``application.provisioning.ports.SyncOrderRepository``.

    Exists because payment approval runs in the synchronous scope, and the order
    must move to PAID inside the same transaction that approves the payment.
    Splitting them across two connections is how a customer ends up paid and
    serviceless.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_invoice(self, invoice_id: str) -> Order | None:
        stmt = select(OrderModel).where(OrderModel.invoice_id == invoice_id)
        row = self._session.execute(stmt).scalar_one_or_none()
        return order_to_domain(row) if row else None

    def get(self, order_id: str) -> Order | None:
        row = self._session.get(OrderModel, order_id)
        return order_to_domain(row) if row else None

    def update(self, order: Order) -> None:
        row = self._session.get(OrderModel, order.id)
        if row is None:
            raise NotFoundError("Order not found.", order_id=order.id)
        order_apply(row, order)
        self._session.flush()
