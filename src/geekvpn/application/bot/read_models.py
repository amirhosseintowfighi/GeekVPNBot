"""Flat read models for bot screens.

Every field here exists because some screen renders it. There is no "might be
useful later" data, because each extra field is one more thing a fake has to
fill in for a test to compile.

Amounts are plain int tomans; the UI layer owns Persian formatting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from geekvpn.domain.catalog.rewards import LoyaltyTier


class SubscriptionState(str, Enum):
    ACTIVE = "active"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    SUSPENDED = "suspended"
    PENDING = "pending"

    @property
    def is_usable(self) -> bool:
        return self in (SubscriptionState.ACTIVE, SubscriptionState.EXPIRING)


class TransactionKind(str, Enum):
    TOPUP = "topup"
    PURCHASE = "purchase"
    CASHBACK = "cashback"
    REFERRAL = "referral"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class PaymentMethod(str, Enum):
    WALLET = "wallet"
    CARD = "card"
    CRYPTO = "crypto"
    GATEWAY = "gateway"


class PaymentState(str, Enum):
    AWAITING_PROOF = "awaiting_proof"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ServerHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    MAINTENANCE = "maintenance"


class TicketState(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"
    WAITING = "waiting"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SubscriptionCard:
    subscription_id: uuid.UUID
    plan_id: uuid.UUID
    product_name_fa: str
    plan_name_fa: str
    state: SubscriptionState
    expires_at: datetime | None = None
    quota_gib: int | None = None
    used_gib: float = 0.0
    device_limit: int = 2
    subscription_url: str | None = None
    created_at: datetime | None = None

    @property
    def is_unlimited(self) -> bool:
        return self.quota_gib is None

    @property
    def usage_fraction(self) -> float:
        """0.0 to 1.0. Unlimited plans report 0 - there is no bar to draw."""
        if self.quota_gib is None or self.quota_gib <= 0:
            return 0.0
        return min(1.0, self.used_gib / self.quota_gib)

    @property
    def remaining_gib(self) -> float | None:
        if self.quota_gib is None:
            return None
        return max(0.0, self.quota_gib - self.used_gib)

    @property
    def is_renewable(self) -> bool:
        """Suspended subscriptions are excluded on purpose.

        Letting someone renew a suspended line takes their money without
        fixing the reason it was suspended.
        """
        return self.state is not SubscriptionState.SUSPENDED


@dataclass(frozen=True, slots=True)
class WalletSnapshot:
    balance: int = 0
    lifetime_spend: int = 0
    pending_credit: int = 0
    #: Derived from lifetime spend, not stored. Shown on the home screen
    #: and the profile ladder, both of which read bronze for everyone
    #: while this was missing.
    tier: LoyaltyTier = LoyaltyTier.BRONZE


@dataclass(frozen=True, slots=True)
class WalletTransaction:
    transaction_id: uuid.UUID
    kind: TransactionKind
    amount: int
    created_at: datetime
    description_fa: str = ""
    balance_after: int | None = None

    @property
    def is_credit(self) -> bool:
        return self.kind in (
            TransactionKind.TOPUP,
            TransactionKind.CASHBACK,
            TransactionKind.REFERRAL,
            TransactionKind.REFUND,
        )


@dataclass(frozen=True, slots=True)
class ReferralSummary:
    code: str
    invited_count: int = 0
    converted_count: int = 0
    total_earned: int = 0
    pending_earned: int = 0

    @property
    def conversion_percent(self) -> int:
        if self.invited_count <= 0:
            return 0
        return int(self.converted_count * 100 / self.invited_count)


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    user_id: uuid.UUID
    telegram_id: int
    #: Shown on the profile screen so a customer can share it without first
    #: navigating to the referral page.
    referral_code: str = ""
    display_name: str | None = None
    username: str | None = None
    phone: str | None = None
    joined_at: datetime | None = None
    order_count: int = 0
    lifetime_spend: int = 0


@dataclass(frozen=True, slots=True)
class ServerStatusRow:
    name_fa: str
    health: ServerHealth
    location_fa: str | None = None
    load_percent: int | None = None
    flag: str | None = None


@dataclass(frozen=True, slots=True)
class TicketCard:
    ticket_id: uuid.UUID
    reference: str
    topic_fa: str
    state: TicketState
    created_at: datetime
    last_message_fa: str = ""
    unread_count: int = 0
    #: When the thread last moved, from either side. The support list
    #: sorts and labels by this and falls back to `created_at`.
    last_reply_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TicketMessageCard:
    """One message in a support thread, as the bot renders it.

    `from_support` rather than the raw kind: the bot draws two sides of a
    conversation and internal notes never reach it, so a boolean is the whole
    of what the screen needs.
    """

    message_id: uuid.UUID
    from_support: bool
    body_fa: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PendingPayment:
    """A payment intent awaiting proof or admin review.

    `reference` is the short human-readable handle the customer quotes to
    support; `payment_id` is what the system uses. Never show the UUID.
    """

    payment_id: uuid.UUID
    reference: str
    amount: int
    method: PaymentMethod
    state: PaymentState
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CardPaymentDetails:
    card_number: str
    card_holder_fa: str
    bank_fa: str
    review_sla_fa: str
    payment: PendingPayment | None = None


@dataclass(frozen=True, slots=True)
class CryptoPaymentDetails:
    network: str
    asset: str
    amount_display: str
    address: str
    payment: PendingPayment | None = None


@dataclass(frozen=True, slots=True)
class NotificationPreferences:
    """Per-user notification switches.

    Immutable, and `with_toggled` returns a new instance. That makes the
    settings handler's "did anything actually change?" check a plain identity
    comparison instead of a diff.
    """

    expiry: bool = True
    traffic: bool = True
    promos: bool = True
    news: bool = True
    quiet_hours: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "expiry": self.expiry,
            "traffic": self.traffic,
            "promos": self.promos,
            "news": self.news,
            "quiet_hours": self.quiet_hours,
        }

    def with_toggled(self, key: str) -> NotificationPreferences:
        """Return a copy with `key` flipped.

        An unknown key returns `self` *by identity*, which is how the caller
        detects a stale button from an older deploy without needing a
        separate error channel.
        """
        current = self.as_dict()
        if key not in current:
            return self
        current[key] = not current[key]
        return NotificationPreferences(**current)

    def allows(self, key: str) -> bool:
        return bool(self.as_dict().get(key, True))
