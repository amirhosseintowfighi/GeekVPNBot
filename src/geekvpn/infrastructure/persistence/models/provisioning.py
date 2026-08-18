"""Orders, subscriptions, nodes and referrals.

These tables were implied by every other context -- analytics reports on them,
the bot renders them, the reminder jobs read them -- but were never written
down. They are the spine the rest of the platform hangs from.

Schema decisions worth defending:

* **An order and an invoice are different things.** The invoice is what the
  customer owes; the order is what we promised to deliver. A refunded order
  still had an invoice, and a free trial has an order with no invoice at all.
* **Traffic is stored in MiB as ``BigInteger``.** Panels speak bytes, customers
  speak gigabytes, and GiB as a float loses a fraction of a gigabyte per row --
  which is a support ticket when the customer is at 99%.
* **``expires_at`` is indexed with ``state``.** Expiry reminders, the churn
  query and the "expiring soon" audience all scan exactly that pair.
* **The panel account is remembered by remote id, not by username.** Usernames
  are editable in every panel we support; the remote id is not.
* **Referrals are edges, not a counter on the user.** "Who did this customer
  bring, and did they pay?" is the whole referral programme.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.infrastructure.persistence.base import Base, TimestampMixin
from geekvpn.infrastructure.persistence.types import EncryptedString

ORDER_STATES = (
    "pending",  # created, awaiting payment
    "paid",  # money in, not yet provisioned
    "provisioning",  # panel call in flight
    "active",  # delivered
    "failed",  # provisioning failed; money must be returned or retried
    "cancelled",
    "refunded",
)

SUBSCRIPTION_STATES = (
    "active",
    "expired",
    "exhausted",  # traffic used up before the date ran out
    "suspended",  # operator action
    "revoked",  # refunded or fraud
)

NODE_STATES = ("online", "degraded", "offline", "maintenance", "retired")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class OrderModel(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)

    plan_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    #: Frozen at purchase time. A plan renamed next month must not rewrite the
    #: customer's order history.
    plan_name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_mib: Mapped[int | None] = mapped_column(BigInteger)
    device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    list_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    coupon_code: Mapped[str | None] = mapped_column(String(64), index=True)

    invoice_id: Mapped[str | None] = mapped_column(String(64), index=True)
    #: True when this order renews an existing subscription. Renewal rate and
    #: churn are both computed from this column.
    is_renewal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    renews_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)

    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(512))
    #: Where the customer came from: 'bot', 'miniapp', 'admin'. Conversion
    #: analysis is meaningless without it.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="bot", index=True)

    __table_args__ = (
        CheckConstraint(f"state IN ({_quoted(ORDER_STATES)})", name="orders_state"),
        CheckConstraint("total >= 0 AND discount >= 0", name="orders_amounts_non_negative"),
        CheckConstraint("duration_days > 0", name="orders_duration_positive"),
        Index("ix_orders_paid_at_state", "paid_at", "state"),
        Index("ix_orders_user_placed", "user_id", "placed_at"),
    )


class SubscriptionModel(TimestampMixin, Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)

    node_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("nodes.id", ondelete="SET NULL"), index=True
    )
    #: Identity on the remote panel. ``remote_id`` is authoritative; the
    #: username is a convenience for operators reading panel logs.
    remote_id: Mapped[str | None] = mapped_column(String(128), index=True)
    remote_username: Mapped[str | None] = mapped_column(String(128))
    subscription_url: Mapped[str | None] = mapped_column(String(512))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: Null means unlimited. Zero would mean "no traffic at all", which is a
    #: different and much angrier customer.
    traffic_limit_mib: Mapped[int | None] = mapped_column(BigInteger)
    traffic_used_mib: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Which reminder thresholds have already fired, e.g. ``[7, 3]`` and
    #: ``[80]``. Kept on the row so a restarted job does not re-notify.
    notified_expiry_days: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    notified_traffic_percents: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason_fa: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        CheckConstraint(f"state IN ({_quoted(SUBSCRIPTION_STATES)})", name="subscriptions_state"),
        CheckConstraint("traffic_used_mib >= 0", name="subscriptions_used_non_negative"),
        CheckConstraint("expires_at > started_at", name="subscriptions_dates_ordered"),
        # One order buys one service. Without this, two concurrent
        # provisions of the same order both insert, and the customer gets
        # two accounts on two nodes for one payment - with only one of them
        # reachable through get_by_order afterwards.
        UniqueConstraint("order_id", name="uq_subscriptions_order"),
        # Expiry reminders, churn, and the "expiring soon" audience.
        Index("ix_subscriptions_state_expires", "state", "expires_at"),
        Index("ix_subscriptions_user_state", "user_id", "state"),
    )


class NodeModel(TimestampMixin, Base):
    """A VPN panel instance we sell capacity on."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    panel_kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(256), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="online", index=True)

    #: Panel credentials. The username stays readable so an operator can find
    #: the account in the panel's own UI without decrypting anything; the
    #: password is encrypted with its own AEAD context so a ciphertext from
    #: another table cannot be pasted here and decrypted.
    username: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_encrypted: Mapped[str | None] = mapped_column(EncryptedString("node.password"))
    verify_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Per-adapter extras: Marzban inbounds, Marzneshin service ids, PasarGuard
    #: groups. Opaque on purpose - a column per panel would mean adding a panel
    #: edits shipped code, which is what the plugin architecture exists to avoid.
    config_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    timeout_seconds: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=15.0)

    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    account_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    traffic_used_mib: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    #: True while the node still accepts new customers. A full node stays
    #: online for existing subscribers but stops being a provisioning target.
    accepting_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(512))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(f"state IN ({_quoted(NODE_STATES)})", name="nodes_state"),
        CheckConstraint("capacity >= 0 AND account_count >= 0", name="nodes_counts_non_negative"),
        CheckConstraint(
            "state <> 'online' OR accepting_new IS FALSE OR password_encrypted IS NOT NULL",
            name="nodes_online_requires_credentials",
        ),
    )


class ReferralModel(TimestampMixin, Base):
    """One row per invited customer. An edge, not a counter."""

    __tablename__ = "referrals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    invitee_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: Set on the invitee's first paid order. Until then this is a signup, not
    #: a conversion, and the two must never be added together.
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_order_id: Mapped[str | None] = mapped_column(String(64))

    #: What the programme actually cost us on this edge.
    reward_paid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    invitee_bonus_paid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: What the invitee has spent, so return on spend is one query.
    revenue_generated: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("referrer_id <> invitee_id", name="referrals_no_self_referral"),
        CheckConstraint("reward_paid >= 0", name="referrals_reward_non_negative"),
        UniqueConstraint("invitee_id", name="uq_referrals_invitee"),
        Index("ix_referrals_referrer_converted", "referrer_id", "converted_at"),
    )


class FunnelEventModel(Base):
    """Storefront funnel telemetry.

    Conversion cannot be reconstructed from orders: an order only exists once
    the customer has already decided. The three stages before that leave no
    other trace, so they are recorded here, one narrow row each.
    """

    __tablename__ = "funnel_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="bot")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        # Distinct users per stage in a date range: the funnel query, exactly.
        Index("ix_funnel_stage_occurred", "stage", "occurred_at"),
        Index("ix_funnel_user_stage", "user_id", "stage"),
    )
