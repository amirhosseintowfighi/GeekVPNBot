"""Concrete readers behind the bot's ports.

``application/bot/ports.py`` declared eight Protocols and nothing ever
implemented them, so ``BotServices`` could not be assembled and every handler
received ``None``. These are the implementations for the ports whose data lives
in the asynchronous scope.

Two impedance mismatches are resolved here rather than pushed onto the handlers:

* The ports identify a customer by the ``User`` aggregate id (a UUID), while
  orders, subscriptions and wallets key on the Telegram id (an int). The
  translation happens once, in :func:`_telegram_id`.
* A :class:`SubscriptionCard` shows the product and plan names, which the
  subscription row does not carry. They come from the order that created it,
  which is the only place they were recorded verbatim.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.bot.read_models import (
    ProfileSummary,
    ReferralSummary,
    ServerHealth,
    ServerStatusRow,
    SubscriptionCard,
)
from geekvpn.application.bot.read_models import (
    SubscriptionState as CardState,
)
from geekvpn.domain.provisioning.enums import NodeState, SubscriptionState
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.persistence.models.provisioning import ReferralModel
from geekvpn.infrastructure.persistence.repositories.nodes import SqlAlchemyNodeRepository
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SqlAlchemyOrderRepository,
    SqlAlchemySubscriptionRepository,
)
from geekvpn.infrastructure.persistence.repositories.user import SqlAlchemyUserRepository

#: The read models speak GiB because that is what the customer is sold; storage
#: is MiB because panels report bytes.
MIB_PER_GIB = 1024

#: ``CardState.EXPIRING`` is deliberately absent: "about to expire" is a
#: function of the clock, not a stored fact, and the renderer derives it.
#: ``REVOKED`` presents as suspended - both mean "we turned it off".
_CARD_STATE: dict[SubscriptionState, CardState] = {
    SubscriptionState.ACTIVE: CardState.ACTIVE,
    SubscriptionState.EXPIRED: CardState.EXPIRED,
    SubscriptionState.EXHAUSTED: CardState.EXHAUSTED,
    SubscriptionState.SUSPENDED: CardState.SUSPENDED,
    SubscriptionState.REVOKED: CardState.SUSPENDED,
}

_NODE_HEALTH: dict[NodeState, ServerHealth] = {
    NodeState.ONLINE: ServerHealth.HEALTHY,
    NodeState.DEGRADED: ServerHealth.DEGRADED,
    NodeState.OFFLINE: ServerHealth.DOWN,
    NodeState.MAINTENANCE: ServerHealth.MAINTENANCE,
    NodeState.RETIRED: ServerHealth.DOWN,
}


class SqlSubscriptionCardReader:
    """Implements ``SubscriptionReader``."""

    def __init__(
        self,
        *,
        users: SqlAlchemyUserRepository,
        subscriptions: SqlAlchemySubscriptionRepository,
        orders: SqlAlchemyOrderRepository,
    ) -> None:
        self._users = users
        self._subscriptions = subscriptions
        self._orders = orders

    async def list_for_user(self, user_id: uuid.UUID) -> list[SubscriptionCard]:
        telegram_id = await _telegram_id(self._users, user_id)
        if telegram_id is None:
            return []

        cards: list[SubscriptionCard] = []
        for subscription in await self._subscriptions.list_for_user(telegram_id):
            order = await self._orders.get(subscription.order_id)
            cards.append(to_card(subscription, order))
        return cards

    async def rotate_link(self, user_id: uuid.UUID, subscription_id: uuid.UUID) -> SubscriptionCard:
        """Not implemented: a fresh link is a panel call, not a read.

        Raising is deliberate. Returning the existing card would tell the
        customer their link was rotated while the leaked one still works, which
        is worse than an error for the single case rotation exists for.
        """
        raise NotImplementedError(
            "Link rotation needs a panel adapter call; see docs/next-tasks.md."
        )


class SqlProfileReader:
    """Implements ``ProfileReader``."""

    def __init__(
        self,
        *,
        users: SqlAlchemyUserRepository,
        orders: SqlAlchemyOrderRepository,
    ) -> None:
        self._users = users
        self._orders = orders

    async def summary(self, user_id: uuid.UUID) -> ProfileSummary:
        user = await self._users.get(user_id)
        if user is None:
            raise LookupError(f"No user {user_id}.")
        return ProfileSummary(
            user_id=user.id,
            telegram_id=user.telegram_id,
            referral_code=user.referral_code,
            display_name=user.display_name,
            username=user.username,
            joined_at=user.created_at,
            order_count=await self._orders.count_for_user(user.telegram_id),
        )

    async def set_display_name(self, user_id: uuid.UUID, display_name: str) -> ProfileSummary:
        """``display_name`` is derived from the name parts, so this writes those.

        The other fields are passed through unchanged: `refresh_profile` treats
        every argument as authoritative, so omitting one would blank it.
        """
        user = await self._users.get(user_id)
        if user is None:
            raise LookupError(f"No user {user_id}.")
        user.refresh_profile(
            username=user.username,
            first_name=display_name,
            last_name=None,
        )
        await self._users.update(user)
        return await self.summary(user_id)


class SqlServerStatusReader:
    """Implements ``ServerStatusReader``.

    Lists only sellable nodes. A customer reading a status page is deciding
    whether to buy, and a node they can never be placed on is noise.
    """

    def __init__(self, *, nodes: SqlAlchemyNodeRepository) -> None:
        self._nodes = nodes

    async def rows(self) -> list[ServerStatusRow]:
        return [
            ServerStatusRow(
                name_fa=node.name_fa,
                health=_NODE_HEALTH.get(node.state, ServerHealth.MAINTENANCE),
                location_fa=node.country_code,
                load_percent=_load_percent(node.load_ratio, node.capacity),
            )
            for node in await self._nodes.list_sellable()
        ]


class SqlReferralSummaryReader:
    """Implements ``ReferralReader``.

    Per-customer, unlike ``analytics.SqlReferralReader`` which aggregates the
    whole programme over a date range. One query: the referral table is an edge
    per invitee, so signups, conversions and cost are three aggregates over the
    same rows.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        users: SqlAlchemyUserRepository,
    ) -> None:
        self._session = session
        self._users = users

    async def summary(self, user_id: uuid.UUID) -> ReferralSummary:
        user = await self._users.get(user_id)
        if user is None:
            raise LookupError(f"No user {user_id}.")

        row = (
            await self._session.execute(
                select(
                    func.count(ReferralModel.id),
                    func.count(ReferralModel.converted_at),
                    func.coalesce(func.sum(ReferralModel.reward_paid), 0),
                ).where(ReferralModel.referrer_id == user.telegram_id)
            )
        ).one()
        invited, converted, earned = row

        return ReferralSummary(
            code=user.referral_code,
            invited_count=int(invited),
            converted_count=int(converted),
            total_earned=int(earned),
            # No column records an accrued-but-unpaid reward: `reward_paid` is
            # written at the moment the wallet is credited. Reporting anything
            # here would be inventing a number, so it stays zero until the
            # programme grows a payout queue.
            pending_earned=0,
        )


async def _telegram_id(users: SqlAlchemyUserRepository, user_id: uuid.UUID) -> int | None:
    user = await users.get(user_id)
    return user.telegram_id if user else None


def _load_percent(load_ratio: float, capacity: int) -> int | None:
    """``None`` for an uncapped node - a bar with no ceiling means nothing."""
    if capacity <= 0:
        return None
    return int(min(1.0, load_ratio) * 100)


def to_card(subscription: Subscription, order: Order | None) -> SubscriptionCard:
    quota_mib = subscription.traffic_limit_mib
    return SubscriptionCard(
        subscription_id=_as_uuid(subscription.id),
        plan_id=_as_uuid(subscription.plan_id),
        product_name_fa=order.plan_name_fa if order else "",
        plan_name_fa=order.plan_name_fa if order else "",
        state=_CARD_STATE.get(subscription.state, CardState.PENDING),
        expires_at=subscription.expires_at,
        quota_gib=None if quota_mib is None else quota_mib // MIB_PER_GIB,
        used_gib=subscription.traffic_used_mib / MIB_PER_GIB,
        device_limit=subscription.device_limit,
        subscription_url=subscription.subscription_url,
        created_at=subscription.started_at,
    )


def _as_uuid(value: str) -> uuid.UUID:
    """Ids are stored as strings; the read models declare UUIDs.

    A non-UUID id becomes the nil UUID rather than raising, because one
    malformed row must not blank the customer's entire service list.
    """
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(int=0)


__all__ = [
    "SqlProfileReader",
    "SqlReferralSummaryReader",
    "SqlServerStatusReader",
    "SqlSubscriptionCardReader",
    "to_card",
]
