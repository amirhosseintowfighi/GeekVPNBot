"""Notification tables: deliveries, preferences, broadcasts, job schedule.

Schema decisions worth defending:

* **A notification row carries its rendered text.** Re-rendering from a template
  key months later would produce a different message than the customer was
  actually sent, which makes the inbox a work of fiction.
* **Delivery attempts are JSONB on the notification.** One notification fans out
  to at most two channels, and the pair is always read together.
* **Preferences default to on and are stored per user, not per category row.**
  Five booleans do not deserve five rows.
* **Suppression is a first-class outcome.** "Muted" and "quiet hours" are
  normal, not failures, and reporting must be able to tell them apart from a
  Telegram 403.
* **The schedule lives in the database.** Cron in a container image cannot be
  paused by an operator at 3am; a row with ``enabled = false`` can.
"""

from __future__ import annotations

import enum
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    DeliveryState,
    JobKind,
    NotificationCategory,
)
from geekvpn.infrastructure.persistence.base import Base, TimestampMixin


def _values(enum_type: type[enum.Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


class NotificationModel(TimestampMixin, Base):
    __tablename__ = "notify_notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    #: Which shop this belongs to. NULL is the platform's own, which is every
    #: row that predates resellers.
    #:
    #: Beside the Telegram id rather than instead of it: the id is what a
    #: notification is delivered to, and a synthetic key would break every
    #: send. The pair is what identifies a person - the same account is a
    #: separate customer in each shop, with their own money.
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    title_fa: Mapped[str] = mapped_column(String(256), nullable=False)
    body_fa: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String(256))

    #: ``[{"channel": "telegram", "state": "sent", "attempts": 1, ...}]``
    deliveries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    #: Denormalised from ``deliveries`` so the inbox and the reporting queries
    #: do not have to open JSON on every row.
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DeliveryState.PENDING.value, index=True
    )
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    send_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    broadcast_id: Mapped[str | None] = mapped_column(String(64), index=True)
    #: Deduplication handle, e.g. ``expiry:3:<subscription id>``. A reminder job
    #: that runs twice must not message the customer twice.
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    #: What produced this notification (a job name, "broadcast", a use
    #: case). Kept for support: "why did I get this?" is unanswerable
    #: without it.
    source: Mapped[str | None] = mapped_column(String(64), index=True)

    __table_args__ = (
        CheckConstraint(
            f"category IN ({_values(NotificationCategory)})", name="notify_notifications_category"
        ),
        CheckConstraint(f"state IN ({_values(DeliveryState)})", name="notify_notifications_state"),
        UniqueConstraint("user_id", "dedupe_key", name="uq_notify_user_dedupe"),
        # The Mini App inbox: newest first for one user.
        Index("ix_notify_user_queued", "user_id", "queued_at"),
        # The deferred flush job.
        Index("ix_notify_state_send_after", "state", "send_after"),
    )


class NotificationPreferenceModel(TimestampMixin, Base):
    __tablename__ = "notify_preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: Which shop this belongs to. NULL is the platform's own, which is every
    #: row that predates resellers.
    #:
    #: Beside the Telegram id rather than instead of it: the id is what a
    #: notification is delivered to, and a synthetic key would break every
    #: send. The pair is what identifies a person - the same account is a
    #: separate customer in each shop, with their own money.
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="SET NULL")
    )
    expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    traffic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    promos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: On by default. Off by default once silently disabled every broadcast in
    #: the platform, which is why this column has a comment.
    news: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    telegram: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    miniapp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    quiet_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quiet_start_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=23)
    quiet_end_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=8)

    __table_args__ = (
        CheckConstraint(
            "quiet_start_hour BETWEEN 0 AND 23 AND quiet_end_hour BETWEEN 0 AND 23",
            name="notify_preferences_quiet_hours_range",
        ),
    )


class BroadcastModel(TimestampMixin, Base):
    __tablename__ = "notify_broadcasts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title_fa: Mapped[str] = mapped_column(String(256), nullable=False)
    body_fa: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default=NotificationCategory.NEWS.value
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BroadcastState.DRAFT.value, index=True
    )

    #: Which shop composed it. NULL is the platform's own.
    #:
    #: It decides two things at once: whose customers the audience resolves
    #: over, and which bot the message is sent from. A broadcast without it
    #: would go to everybody, from us.
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="SET NULL"), index=True
    )

    audience_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Tier name for TIER, explicit user ids for EXPLICIT, empty otherwise.
    audience_filter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped[int | None] = mapped_column(BigInteger)
    cancelled_by: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        CheckConstraint(f"state IN ({_values(BroadcastState)})", name="notify_broadcasts_state"),
        CheckConstraint(
            f"audience_kind IN ({_values(AudienceKind)})", name="notify_broadcasts_audience"
        ),
        CheckConstraint(
            f"category IN ({_values(NotificationCategory)})", name="notify_broadcasts_category"
        ),
        # The dispatcher: what is due to go out.
        Index("ix_notify_broadcasts_state_scheduled", "state", "scheduled_for"),
    )


class ScheduledJobModel(TimestampMixin, Base):
    __tablename__ = "notify_jobs"

    job: Mapped[str] = mapped_column(String(32), primary_key=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(512))
    #: Held by whichever worker is running the job, so two replicas of the
    #: scheduler cannot both fire the expiry reminder.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"job IN ({_values(JobKind)})", name="notify_jobs_kind"),
        CheckConstraint("interval_minutes > 0", name="notify_jobs_interval_positive"),
    )
