"""Turning an ``AudienceKind`` into Telegram ids, in SQL.

The missing half of broadcasts. ``BroadcastService`` has always taken an
``AudienceResolver``; nothing implemented it against the database, so no router
could be built on the service and the admin panel's broadcast screen posted to
routes that did not exist.

Three things this does deliberately:

* **Suspended and banned customers are never in an audience.** A promotional
  message to somebody whose account you have just closed is the single most
  reliable way to turn a quiet suspension into a support thread.
* **Every query is capped.** ``MAX_AUDIENCE`` is not a page size - a broadcast
  is sent in one pass - it is a guard against an operator selecting "everyone"
  on a database that has grown past what Telegram will accept in a sitting.
* **Ordering is by id, not by recency.** A resolve that runs twice must return
  the same list in the same order, or a resumed broadcast re-sends the head of
  it and skips the tail.

Sync, not async: broadcasts live on the synchronous scope alongside payments
and notifications - see the two-scope note in CLAUDE.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from geekvpn.domain.catalog.rewards import TIER_THRESHOLDS, LoyaltyTier
from geekvpn.domain.identity.enums import UserStatus
from geekvpn.domain.notifications.enums import AudienceKind
from geekvpn.domain.notifications.errors import UnknownAudience
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)

#: Hard ceiling on one audience. Telegram's own limits make a larger single
#: broadcast a bad idea regardless of what the database could return.
MAX_AUDIENCE = 50_000

#: What "expiring soon" means, matching the reminder sweep's widest window so
#: the two never disagree about who is about to lapse.
EXPIRING_WITHIN_DAYS = 7

#: Order states that represent money actually taken.
PAID_ORDER_STATES = ("paid", "provisioning", "active")


class SqlAudienceResolver:
    """``AudienceResolver`` over the live schema."""

    def __init__(self, session: Session, *, limit: int = MAX_AUDIENCE) -> None:
        self._session = session
        self._limit = limit

    def resolve(self, audience: AudienceKind, *, reference: str | None = None) -> list[int]:
        now = datetime.now(UTC)

        if audience is AudienceKind.EXPLICIT:
            return self._explicit(reference)

        statement = self._reachable()

        if audience is AudienceKind.ALL:
            pass
        elif audience is AudienceKind.ACTIVE_SUBSCRIBERS:
            statement = statement.where(
                UserModel.telegram_id.in_(self._with_live_subscription(now))
            )
        elif audience is AudienceKind.EXPIRED:
            # Everyone whose last subscription has lapsed, and who has not since
            # started another one. Without the second half, a customer who
            # renewed yesterday still receives "your service has ended".
            statement = statement.where(
                UserModel.telegram_id.in_(self._with_expired_subscription(now)),
                UserModel.telegram_id.not_in(self._with_live_subscription(now)),
            )
        elif audience is AudienceKind.EXPIRING_SOON:
            statement = statement.where(
                UserModel.telegram_id.in_(self._expiring_within(EXPIRING_WITHIN_DAYS, now))
            )
        elif audience is AudienceKind.NEVER_PURCHASED:
            statement = statement.where(UserModel.telegram_id.not_in(self._with_paid_order()))
        elif audience is AudienceKind.TIER:
            statement = statement.where(UserModel.telegram_id.in_(self._in_tier(reference)))
        else:  # pragma: no cover - the enum is exhaustive above
            raise UnknownAudience(f"No rule for audience {audience}.", audience=str(audience))

        rows = self._session.execute(statement.limit(self._limit)).scalars().all()
        return list(rows)

    # ---- building blocks ------------------------------------------------

    def _reachable(self) -> Select[tuple[int]]:
        """Active customers only, in a stable order.

        A suspended or banned account is not an audience member: they are
        excluded here rather than at each call site so no future audience can
        forget to.
        """
        return (
            select(UserModel.telegram_id)
            .where(UserModel.status == UserStatus.ACTIVE.value)
            .order_by(UserModel.telegram_id)
        )

    def _with_live_subscription(self, now: datetime) -> Select[tuple[int]]:
        return select(SubscriptionModel.user_id).where(
            SubscriptionModel.state == "active",
            SubscriptionModel.expires_at > now,
        )

    def _with_expired_subscription(self, now: datetime) -> Select[tuple[int]]:
        return select(SubscriptionModel.user_id).where(
            or_(
                SubscriptionModel.state.in_(("expired", "exhausted")),
                and_(SubscriptionModel.state == "active", SubscriptionModel.expires_at <= now),
            )
        )

    def _expiring_within(self, days: int, now: datetime) -> Select[tuple[int]]:
        return select(SubscriptionModel.user_id).where(
            SubscriptionModel.state == "active",
            SubscriptionModel.expires_at > now,
            SubscriptionModel.expires_at <= now + timedelta(days=days),
        )

    def _with_paid_order(self) -> Select[tuple[int]]:
        return select(OrderModel.user_id).where(OrderModel.state.in_(PAID_ORDER_STATES))

    def _in_tier(self, reference: str | None) -> Select[tuple[int]]:
        """Lifetime spend, bucketed by the same thresholds the storefront uses.

        Computed rather than stored: a tier column would be a second source of
        truth that drifts the moment a refund lands.
        """
        tier = _tier_from(reference)
        floor = TIER_THRESHOLDS[tier]
        ceilings = [value for value in TIER_THRESHOLDS.values() if value > floor]

        spend = func.coalesce(func.sum(OrderModel.total), 0)
        statement = (
            select(OrderModel.user_id)
            .where(OrderModel.state.in_(PAID_ORDER_STATES))
            .group_by(OrderModel.user_id)
            .having(spend >= floor)
        )
        if ceilings:
            # Bounded above by the next tier, so "silver" means silver and not
            # "silver and everyone richer".
            statement = statement.having(spend < min(ceilings))
        return statement

    def _explicit(self, reference: str | None) -> list[int]:
        """A hand-supplied list, as comma-separated Telegram ids.

        Still filtered through `_reachable`: an operator pasting ids from a
        spreadsheet has no way to know which of them are suspended.
        """
        if not reference:
            return []
        wanted = {
            int(part)
            for part in reference.replace(" ", "").split(",")
            if part.lstrip("-").isdigit()
        }
        if not wanted:
            return []
        statement = self._reachable().where(UserModel.telegram_id.in_(wanted))
        return list(self._session.execute(statement.limit(self._limit)).scalars().all())


def _tier_from(reference: str | None) -> LoyaltyTier:
    try:
        return LoyaltyTier(str(reference))
    except ValueError:
        raise UnknownAudience(
            f"'{reference}' is not a loyalty tier.",
            audience=str(AudienceKind.TIER),
        ) from None


__all__ = ["EXPIRING_WITHIN_DAYS", "MAX_AUDIENCE", "SqlAudienceResolver"]
