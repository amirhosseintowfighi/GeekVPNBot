"""Billing tables: invoices, payments, refunds, wallet ledger, receipts.

Schema decisions worth defending:

* **Money is ``BigInteger``.** Same rule as the catalog: whole Toman, never a
  float. An invoice that reads 989,999.9999998 is a support ticket.
* **The wallet has no balance column.** A balance column and a ledger disagree
  eventually, and when they do there is no way to tell which one lied. The
  balance is ``balance_after`` of the newest entry, and every entry carries the
  running total so a corrupted row is visible rather than silently absorbed.
* **Refunds are rows, not a counter.** Partial refunds are normal here, and
  "how much of this payment is still refundable" must be answerable from the
  database alone.
* **Receipt digests are a table with a unique index.** Duplicate-receipt
  detection has to be a database constraint. Two operators reviewing the same
  forwarded receipt at the same moment is the exact race that a Python check
  loses.
* **Nothing is deleted.** Rejected and expired payments are the audit trail for
  a manual card-to-card flow, which is the whole point of that flow.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.domain.payments.enums import (
    InvoiceState,
    PaymentMethod,
    PaymentState,
    RefundDestination,
    RefundReason,
    TransactionKind,
)
from geekvpn.infrastructure.persistence.base import Base, TimestampMixin


def _values(enum_type: type[enum.Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


class InvoiceModel(TimestampMixin, Base):
    __tablename__ = "billing_invoices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=InvoiceState.OPEN.value, index=True
    )

    #: Denormalised line items. Lines are immutable once issued and are only
    #: ever read as a whole document, so a child table would buy nothing.
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    discount_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    plan_id: Mapped[str | None] = mapped_column(String(64), index=True)
    plan_name: Mapped[str | None] = mapped_column(String(128))
    campaign_id: Mapped[str | None] = mapped_column(String(64), index=True)
    coupon_code: Mapped[str | None] = mapped_column(String(64), index=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    paid_by_payment_id: Mapped[str | None] = mapped_column(String(64))
    notes_fa: Mapped[str | None] = mapped_column(String(512))
    #: What the customer is being billed for, in Persian. The aggregate treats
    #: this as required, so it is NOT NULL here rather than a nullable column
    #: that would fail to load back into the domain.
    subject_fa: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    #: Free-form string map carried by the aggregate. Named ``meta`` because
    #: ``metadata`` is reserved by SQLAlchemy's declarative base.
    meta: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(f"state IN ({_values(InvoiceState)})", name="billing_invoices_state"),
        CheckConstraint("total >= 0", name="billing_invoices_total_positive"),
        Index("ix_billing_invoices_user_state", "user_id", "state"),
        # Revenue reporting always slices by settlement time, never by row age.
        Index("ix_billing_invoices_paid_at_state", "paid_at", "state"),
    )


class PaymentModel(TimestampMixin, Base):
    __tablename__ = "billing_payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("billing_invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PaymentState.DRAFT.value, index=True
    )

    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    captured: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunded_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    gateway_key: Mapped[str | None] = mapped_column(String(32))
    gateway_reference: Mapped[str | None] = mapped_column(String(128))

    #: The submitted proof as a whole document: reference, digest, file id,
    #: network, note. It is written once and read whole by the review screen.
    proof: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, index=True)
    #: Persian rejection reason shown to the customer.
    reason_fa: Mapped[str | None] = mapped_column(String(512))
    #: When a human made the approve/reject decision. Distinct from
    #: ``settled_at``: a gateway settles without anyone reviewing.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Machine-readable failure cause (gateway/system), never shown as-is.
    #: Kept apart from ``reason_fa`` so an operator message is never confused
    #: with a stack-level cause.
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    meta: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(f"method IN ({_values(PaymentMethod)})", name="billing_payments_method"),
        CheckConstraint(f"state IN ({_values(PaymentState)})", name="billing_payments_state"),
        CheckConstraint("amount > 0", name="billing_payments_amount_positive"),
        CheckConstraint(
            "refunded_total >= 0 AND refunded_total <= captured",
            name="billing_payments_refund_within_capture",
        ),
        # The review queue: pending payments oldest first.
        Index("ix_billing_payments_state_created", "state", "created_at"),
        Index("ix_billing_payments_user_state", "user_id", "state"),
    )


class RefundModel(TimestampMixin, Base):
    __tablename__ = "billing_refunds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("billing_payments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    destination: Mapped[str] = mapped_column(String(16), nullable=False)
    note_fa: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    refunded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor_id: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(f"reason IN ({_values(RefundReason)})", name="billing_refunds_reason"),
        CheckConstraint(
            f"destination IN ({_values(RefundDestination)})",
            name="billing_refunds_destination",
        ),
        CheckConstraint("amount > 0", name="billing_refunds_amount_positive"),
    )


class WalletEntryModel(TimestampMixin, Base):
    """Append-only ledger. There is deliberately no wallet table."""

    __tablename__ = "billing_wallet_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    #: Signed: credits positive, debits negative. The domain stores the same
    #: signed integer, so no interpretation happens at the boundary.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    description_fa: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    #: Idempotency handle: the payment id, invoice id or referral id that caused
    #: this entry. Unique per user so a retried credit cannot double-pay.
    reference: Mapped[str | None] = mapped_column(String(128))
    actor_id: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(TransactionKind)})", name="billing_wallet_kind"),
        CheckConstraint("balance_after >= 0", name="billing_wallet_balance_non_negative"),
        CheckConstraint("amount <> 0", name="billing_wallet_amount_non_zero"),
        UniqueConstraint("user_id", "kind", "reference", name="uq_wallet_user_kind_reference"),
        Index("ix_billing_wallet_user_occurred", "user_id", "occurred_at"),
    )


class ReceiptDigestModel(TimestampMixin, Base):
    """One row per receipt ever seen. The unique index is the real defence."""

    __tablename__ = "billing_receipt_digests"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CardAccountModel(TimestampMixin, Base):
    """Destination cards for the manual card-to-card flow."""

    __tablename__ = "billing_card_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    bank_fa: Mapped[str] = mapped_column(String(64), nullable=False)
    card_number: Mapped[str] = mapped_column(String(19), nullable=False, unique=True)
    sheba: Mapped[str | None] = mapped_column(String(26))
    active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    #: Rotation order. The bot shows the lowest sort order that is active, so a
    #: card can be retired without editing code.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_limit: Mapped[int | None] = mapped_column(BigInteger)
