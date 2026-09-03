"""The Subscription aggregate: the thing the customer actually uses.

Units: **traffic is MiB, time is timezone-aware UTC.** Panels report bytes and
sometimes naive local timestamps; the adapter converts at the boundary so this
class never has to ask which unit it was handed. Two units for traffic in one
codebase is how a customer gets billed for a thousand times what they used.

Usage is *replaced*, never accumulated. A panel reports a running total, so
adding deltas would double-count every time a sync ran twice - and syncs do
run twice, because retries exist.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.errors import (
    IllegalSubscriptionTransition,
    OrderValidationError,
    SubscriptionRevoked,
)
from geekvpn.domain.provisioning.events import (
    SubscriptionActivated,
    SubscriptionExhausted,
    SubscriptionExpired,
    SubscriptionRenewed,
    SubscriptionRevokedEvent,
    SubscriptionSuspended,
)

MIB_PER_GIB = 1024

#: Reminder ladders. Kept here rather than in the job so that "have we already
#: told them?" is answered by the aggregate that knows.
EXPIRY_REMINDER_DAYS: tuple[int, ...] = (7, 3, 1)
TRAFFIC_REMINDER_PERCENTS: tuple[int, ...] = (80, 95)


class Subscription(AggregateRoot[str]):
    """One provisioned account on one panel."""

    __slots__ = (
        "_notified_expiry_days",
        "_notified_traffic_percents",
        "_state",
        "device_limit",
        "expires_at",
        "last_synced_at",
        "last_used_at",
        "node_id",
        "order_id",
        "plan_id",
        "remote_id",
        "remote_username",
        "reseller_id",
        "revoke_reason_fa",
        "revoked_at",
        "started_at",
        "subscription_url",
        "suspend_reason_fa",
        "traffic_limit_mib",
        "traffic_used_mib",
        "user_id",
    )

    def __init__(
        self,
        subscription_id: str,
        *,
        user_id: int,
        #: `None` when nobody bought this here - an account sold through
        #: support and claimed in the bot afterwards. Everything else about
        #: such a subscription is ordinary; it simply has no sale behind it.
        order_id: str | None = None,
        plan_id: str | None = None,
        started_at: datetime,
        expires_at: datetime,
        remote_username: str,
        state: SubscriptionState = SubscriptionState.ACTIVE,
        node_id: str | None = None,
        remote_id: str | None = None,
        reseller_id: str | None = None,
        subscription_url: str | None = None,
        traffic_limit_mib: int | None = None,
        traffic_used_mib: int = 0,
        device_limit: int = 2,
        last_synced_at: datetime | None = None,
        last_used_at: datetime | None = None,
        notified_expiry_days: Iterable[int] = (),
        notified_traffic_percents: Iterable[int] = (),
        revoked_at: datetime | None = None,
        revoke_reason_fa: str | None = None,
        suspend_reason_fa: str | None = None,
    ) -> None:
        super().__init__(subscription_id)
        if expires_at <= started_at:
            raise OrderValidationError(
                "A subscription must expire after it starts.",
                started_at=started_at.isoformat(),
                expires_at=expires_at.isoformat(),
            )
        if traffic_used_mib < 0:
            raise OrderValidationError(
                "Used traffic cannot be negative.", traffic_used_mib=traffic_used_mib
            )
        self.user_id = user_id
        self.order_id = order_id
        self.plan_id = plan_id
        self._state = state
        self.node_id = node_id
        self.remote_id = remote_id
        #: Who sold this. ``None`` means the platform did, directly, which
        #: is every subscription that predates resellers.
        self.reseller_id = reseller_id
        #: Why this is suspended, when it is.
        #:
        #: The reason used to exist only on the event, which meant nothing
        #: could ever tell two suspensions apart afterwards - and the
        #: difference matters: a subscription stopped because a reseller
        #: owes us money should come back when they pay, and one stopped
        #: by an operator for abuse must not.
        self.suspend_reason_fa = suspend_reason_fa
        self.remote_username = remote_username
        self.subscription_url = subscription_url
        self.started_at = started_at
        self.expires_at = expires_at
        self.traffic_limit_mib = traffic_limit_mib
        self.traffic_used_mib = traffic_used_mib
        self.device_limit = device_limit
        self.last_synced_at = last_synced_at
        self.last_used_at = last_used_at
        self._notified_expiry_days = set(notified_expiry_days)
        self._notified_traffic_percents = set(notified_traffic_percents)
        self.revoked_at = revoked_at
        self.revoke_reason_fa = revoke_reason_fa

    # ---- Construction ---------------------------------------------------

    @classmethod
    def activate(
        cls,
        subscription_id: str,
        *,
        user_id: int,
        order_id: str,
        plan_id: str,
        remote_username: str,
        now: datetime,
        duration_days: int,
        traffic_limit_mib: int | None = None,
        device_limit: int = 2,
        node_id: str | None = None,
        remote_id: str | None = None,
        subscription_url: str | None = None,
        reseller_id: str | None = None,
    ) -> Subscription:
        subscription = cls(
            subscription_id,
            user_id=user_id,
            order_id=order_id,
            plan_id=plan_id,
            started_at=now,
            expires_at=now + timedelta(days=duration_days),
            remote_username=remote_username,
            reseller_id=reseller_id,
            traffic_limit_mib=traffic_limit_mib,
            device_limit=device_limit,
            node_id=node_id,
            remote_id=remote_id,
            subscription_url=subscription_url,
        )
        subscription.record(
            SubscriptionActivated(
                subscription_id=subscription_id,
                user_id=user_id,
                plan_id=plan_id,
                expires_at=subscription.expires_at.isoformat(),
            )
        )
        return subscription

    @classmethod
    def restore(cls, subscription_id: str, **fields: object) -> Subscription:
        """Rebuild from storage. Records nothing: loading is not an event."""
        return cls(subscription_id, **fields)  # type: ignore[arg-type]

    # ---- Accessors ------------------------------------------------------

    @property
    def state(self) -> SubscriptionState:
        return self._state

    @property
    def is_unlimited(self) -> bool:
        return self.traffic_limit_mib is None or self.traffic_limit_mib <= 0

    @property
    def remaining_mib(self) -> int | None:
        if self.is_unlimited or self.traffic_limit_mib is None:
            return None
        return max(0, self.traffic_limit_mib - self.traffic_used_mib)

    @property
    def used_gib(self) -> float:
        return self.traffic_used_mib / MIB_PER_GIB

    def usage_percent(self) -> float:
        """0-100. An unlimited plan reports 0: there is no bar to draw."""
        if self.is_unlimited or not self.traffic_limit_mib:
            return 0.0
        return min(100.0, self.traffic_used_mib / self.traffic_limit_mib * 100)

    def remaining_days(self, now: datetime) -> int:
        """Whole days left, floored at zero."""
        seconds = (self.expires_at - now).total_seconds()
        return max(0, int(seconds // 86_400))

    def is_expired_at(self, now: datetime) -> bool:
        return now >= self.expires_at

    def is_exhausted(self) -> bool:
        if self.is_unlimited or self.traffic_limit_mib is None:
            return False
        return self.traffic_used_mib >= self.traffic_limit_mib

    def is_usable_at(self, now: datetime) -> bool:
        return (
            self._state is SubscriptionState.ACTIVE
            and not self.is_expired_at(now)
            and not self.is_exhausted()
        )

    # ---- Usage ----------------------------------------------------------

    def _guard_changeable(self) -> None:
        if self._state is SubscriptionState.REVOKED:
            raise SubscriptionRevoked()

    def record_usage(self, *, used_mib: int, at: datetime) -> None:
        """Absolute total from the panel, not a delta."""
        self._guard_changeable()
        if used_mib < 0:
            raise OrderValidationError("Reported usage cannot be negative.", used_mib=used_mib)
        # A panel that was reset reports a smaller number than we already hold.
        # Trusting it would hand back traffic the customer really consumed, so
        # usage only ever moves forward until an explicit reset.
        if used_mib > self.traffic_used_mib:
            self.last_used_at = at
        self.traffic_used_mib = max(self.traffic_used_mib, used_mib)
        self.last_synced_at = at
        if self.is_exhausted() and self._state is SubscriptionState.ACTIVE:
            self._state = SubscriptionState.EXHAUSTED
            self.record(
                SubscriptionExhausted(
                    subscription_id=self.id,
                    user_id=self.user_id,
                    used_mib=self.traffic_used_mib,
                )
            )

    def reset_traffic(self, *, at: datetime) -> None:
        """Deliberate zeroing, e.g. a monthly refill or a goodwill gesture."""
        self._guard_changeable()
        self.traffic_used_mib = 0
        self.last_synced_at = at
        self._notified_traffic_percents.clear()
        if self._state is SubscriptionState.EXHAUSTED:
            self._state = SubscriptionState.ACTIVE

    def add_traffic(self, *, extra_mib: int) -> None:
        self._guard_changeable()
        if self.traffic_limit_mib is None:
            return  # already unlimited; nothing to raise
        self.traffic_limit_mib += extra_mib
        self._notified_traffic_percents.clear()
        if self._state is SubscriptionState.EXHAUSTED and not self.is_exhausted():
            self._state = SubscriptionState.ACTIVE

    # ---- Lifecycle ------------------------------------------------------

    def renew(self, *, days: int, now: datetime, quota_mib: int | None = None) -> None:
        """Extend the term and start a fresh allowance.

        An expired subscription is extended from *now*; a live one from its
        current expiry, so renewing early never costs the customer the days
        they already paid for.

        ``quota_mib`` is the new term's allowance in full, not an increment,
        and usage resets with it. The two readings must agree: the panel is
        given an absolute figure, so a domain that accumulated instead drifted
        one term further from it on every renewal - after two renewals of a
        50GB plan the panel said 50 and the database said 150.

        Resetting rather than rolling over is the deliberate half. Unused
        traffic does not carry forward, which is what "monthly allowance"
        means everywhere else the customer has seen one.
        """
        self._guard_changeable()
        if days <= 0:
            raise OrderValidationError("A renewal must add at least one day.", days=days)
        base = self.expires_at if self.expires_at > now else now
        self.expires_at = base + timedelta(days=days)
        if quota_mib is not None:
            self.traffic_limit_mib = quota_mib
            self.traffic_used_mib = 0
        self._notified_expiry_days.clear()
        if quota_mib is not None:
            self._notified_traffic_percents.clear()
        if (
            self._state in (SubscriptionState.EXPIRED, SubscriptionState.EXHAUSTED)
            and not self.is_exhausted()
        ):
            self._state = SubscriptionState.ACTIVE
        self.record(
            SubscriptionRenewed(
                subscription_id=self.id,
                user_id=self.user_id,
                expires_at=self.expires_at.isoformat(),
                added_days=days,
            )
        )

    def expire(self, *, now: datetime) -> None:
        self._guard_changeable()
        if self._state is SubscriptionState.EXPIRED:
            return
        if self._state not in (
            SubscriptionState.ACTIVE,
            SubscriptionState.EXHAUSTED,
            SubscriptionState.SUSPENDED,
        ):
            raise IllegalSubscriptionTransition(
                current=self._state.value, target=SubscriptionState.EXPIRED.value
            )
        self._state = SubscriptionState.EXPIRED
        self.record(SubscriptionExpired(subscription_id=self.id, user_id=self.user_id))

    def suspend(self, *, reason_fa: str) -> None:
        self._guard_changeable()
        if self._state is SubscriptionState.SUSPENDED:
            return
        self._state = SubscriptionState.SUSPENDED
        self.suspend_reason_fa = reason_fa
        self.record(
            SubscriptionSuspended(
                subscription_id=self.id, user_id=self.user_id, reason_fa=reason_fa
            )
        )

    def resume(self, *, now: datetime) -> None:
        """Lift a suspension, landing in whatever state reality dictates."""
        # Cleared here rather than left behind: a stale reason on an active
        # subscription would resume it a second time on the next sweep.
        self.suspend_reason_fa = None
        self._guard_changeable()
        if self._state is not SubscriptionState.SUSPENDED:
            raise IllegalSubscriptionTransition(
                current=self._state.value, target=SubscriptionState.ACTIVE.value
            )
        if self.is_expired_at(now):
            self._state = SubscriptionState.EXPIRED
        elif self.is_exhausted():
            self._state = SubscriptionState.EXHAUSTED
        else:
            self._state = SubscriptionState.ACTIVE

    def revoke(self, *, reason_fa: str, at: datetime) -> None:
        """Terminal. Used for fraud and for accounts deleted on the panel."""
        if self._state is SubscriptionState.REVOKED:
            return
        self._state = SubscriptionState.REVOKED
        self.revoked_at = at
        self.revoke_reason_fa = reason_fa
        self.record(
            SubscriptionRevokedEvent(
                subscription_id=self.id, user_id=self.user_id, reason_fa=reason_fa
            )
        )

    # ---- Reminder bookkeeping -------------------------------------------

    @property
    def notified_expiry_days(self) -> frozenset[int]:
        return frozenset(self._notified_expiry_days)

    @property
    def notified_traffic_percents(self) -> frozenset[int]:
        return frozenset(self._notified_traffic_percents)

    def due_expiry_reminder(self, *, now: datetime) -> int | None:
        """The reminder to send right now, or None.

        Returns the *smallest* unsent step that has been reached, so a job that
        was down for a week sends "1 day left" rather than a burst of three
        messages the customer reads as spam.
        """
        if self._state is not SubscriptionState.ACTIVE:
            return None
        left = self.remaining_days(now)
        reached = [
            day
            for day in EXPIRY_REMINDER_DAYS
            if left <= day and day not in self._notified_expiry_days
        ]
        return min(reached) if reached else None

    def due_traffic_reminder(self) -> int | None:
        """Highest unsent threshold already crossed, or None."""
        if self.is_unlimited or self._state is not SubscriptionState.ACTIVE:
            return None
        percent = self.usage_percent()
        reached = [
            step
            for step in TRAFFIC_REMINDER_PERCENTS
            if percent >= step and step not in self._notified_traffic_percents
        ]
        return max(reached) if reached else None

    def mark_expiry_notified(self, day: int) -> None:
        """Record a sent reminder, and every looser step it supersedes.

        Sending "1 day left" also answers "7 days left" and "3 days left". If
        only the exact step were recorded, a job that came back after an
        outage would send the urgent message first and the relaxed ones
        afterwards - which reads as spam and, worse, as reassurance.
        """
        for step in EXPIRY_REMINDER_DAYS:
            if step >= day:
                self._notified_expiry_days.add(step)

    def mark_traffic_notified(self, percent: int) -> None:
        """Record a sent warning, and every lower threshold it supersedes."""
        for step in TRAFFIC_REMINDER_PERCENTS:
            if step <= percent:
                self._notified_traffic_percents.add(step)


__all__ = [
    "EXPIRY_REMINDER_DAYS",
    "MIB_PER_GIB",
    "TRAFFIC_REMINDER_PERCENTS",
    "Subscription",
]
