"""Reseller tables.

Four of them, and the split is deliberate:

* `resellers` is the account - who they are, what they are allowed, what they
  have left to spend.
* `reseller_plan_prices` holds the per-package exceptions, because a
  percentage is right for most of a catalogue and wrong at the edges.
* `reseller_nodes` is which panels are theirs. A join table rather than a JSON
  array so the provisioning query can filter in SQL.
* `reseller_ledger` is every movement of credit, because "where did my balance
  go" is the first question a reseller asks and a balance alone cannot answer
  it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.infrastructure.persistence.base import Base, TimestampMixin
from geekvpn.infrastructure.persistence.types import EncryptedString


def _values(enum_type: type[enum.Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


class ResellerModel(TimestampMixin, Base):
    __tablename__ = "resellers"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    #: Their login. One admin account, one reseller - the account is how they
    #: authenticate and this row is what they are allowed to do once they have.
    admin_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admins.id", ondelete="CASCADE"), nullable=False,
        unique=True,
    )
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ResellerStatus.ACTIVE.value, index=True
    )
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Toman, never negative. Debt is a policy decision with a limit and a
    #: settlement process behind it, and this platform has neither yet.
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    #: Their own Telegram bot. Encrypted with its own AEAD context, like panel
    #: passwords: a token is a full credential, and one leaked from a database
    #: dump lets somebody impersonate the reseller to all of their customers.
    bot_token_encrypted: Mapped[str | None] = mapped_column(EncryptedString("reseller.bot_token"))
    #: Readable, so the panel can show "@theirbot" without decrypting anything.
    bot_username: Mapped[str | None] = mapped_column(String(64), unique=True)

    #: What their bot calls itself. NULL falls back to the platform's own
    #: name - correct for our bot, and a reasonable default until a reseller
    #: decides theirs.
    #:
    #: Separate from `name_fa`, which is what *we* call them on the operator
    #: screens. A shop trading as one name and filed under another is normal.
    brand_fa: Mapped[str | None] = mapped_column(String(64))
    contact_fa: Mapped[str | None] = mapped_column(String(256))
    note_fa: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        CheckConstraint(f"status IN ({_values(ResellerStatus)})", name="resellers_status"),
        # 90 rather than 100: a package that costs a reseller nothing is a
        # mistake in a form, and it would drain panel capacity for free.
        CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 90", name="resellers_discount"
        ),
        # No non-negative constraint. A balance may go under through an
        # operator settlement, and the consequence is that the reseller's
        # customers are suspended until it is positive again - which is the
        # credit limit this platform enforces, in place of a number nobody
        # would keep up to date.
    )


class ResellerPlanPriceModel(Base):
    __tablename__ = "reseller_plan_prices"

    reseller_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="CASCADE"), primary_key=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("catalog_plans.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: What the platform charges this reseller. NULL means their percentage
    #: applies, which is the usual case - the exceptions are the edges where a
    #: percentage is the wrong shape.
    price: Mapped[int | None] = mapped_column(BigInteger)
    #: What the reseller charges their own customer. NULL means they have not
    #: decided and the platform's list price stands. Theirs to set to anything,
    #: including below what it costs them.
    retail_price: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        # Zero is allowed here and only here: a giveaway a human typed on
        # purpose, for one package, for one reseller.
        CheckConstraint(
            "price IS NULL OR price >= 0", name="reseller_plan_prices_non_negative"
        ),
        CheckConstraint(
            "retail_price IS NULL OR retail_price >= 0",
            name="reseller_plan_prices_retail_non_negative",
        ),
    )


class ResellerNodeModel(Base):
    __tablename__ = "reseller_nodes"

    reseller_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )


class ResellerLedgerModel(Base):
    """Every movement of a reseller's credit.

    Append-only. A balance is a number somebody will eventually dispute, and
    the only useful answer is the list of things that changed it.
    """

    __tablename__ = "reseller_ledger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reseller_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False
    )
    #: Signed Toman: negative for a sale, positive for a top-up or a refund.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    description_fa: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    #: The subscription, order or payment this entry is about, when there is
    #: one. A string because the ids on the synchronous side are hex, not UUID.
    reference: Mapped[str | None] = mapped_column(String(64), index=True)
    #: Which operator did it, for a manual adjustment. Null for a sale, which
    #: the reseller did themselves.
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", name="reseller_ledger_id_unique"),
        Index("ix_reseller_ledger_reseller_time", "reseller_id", "occurred_at"),
    )


class ResellerApplicationModel(TimestampMixin, Base):
    """Somebody asking to sell under their own name.

    Its own table rather than a ticket. A ticket is a conversation that ends;
    this is a record with a decision attached - and the partial unique index is
    why it cannot be a conversation: one pending application per person,
    enforced by the database rather than by whichever handler remembered.
    """

    __tablename__ = "reseller_applications"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_fa: Mapped[str | None] = mapped_column(String(256))
    note_fa: Mapped[str | None] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    reason_fa: Mapped[str | None] = mapped_column(String(512))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: What this became. Null while pending, and null forever on a rejection.
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')",
            name="ck_reseller_applications_state",
        ),
        Index(
            "uq_reseller_applications_pending",
            "telegram_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ),
    )


class ResellerTopupModel(TimestampMixin, Base):
    """A reseller asking to have their credit topped up.

    Its own table rather than the customer wallet's. A reseller's credit has no
    gateway, no cashback and no refund policy - and the one thing this needs
    that the wallet flow lacks is an operator deciding whether the money
    actually arrived, which is the whole transaction.
    """

    __tablename__ = "reseller_topups"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    reseller_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note_fa: Mapped[str | None] = mapped_column(String(256))
    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_fa: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_reseller_topups_amount"),
        CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')",
            name="ck_reseller_topups_state",
        ),
    )


class ResellerTextModel(Base):
    """One screen a reseller has rewritten.

    Overrides, not copies. Only the screens they changed are stored, so
    improving a message improves it in every shop that has not deliberately
    taken it over - the opposite of seeding each reseller with a frozen
    snapshot of the text file on the day they signed up.
    """

    __tablename__ = "reseller_texts"

    reseller_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="CASCADE"), primary_key=True
    )
    #: The constant's name in `presentation/bot/ui/text.py`.
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    body_fa: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "ResellerApplicationModel",
    "ResellerLedgerModel",
    "ResellerModel",
    "ResellerNodeModel",
    "ResellerPlanPriceModel",
    "ResellerTextModel",
    "ResellerTopupModel",
]


class RequiredChannelModel(TimestampMixin, Base):
    """A channel a customer must join before the bot will serve them.

    Per shop, like every other customer-facing setting. NULL is the platform's
    own bot; a reseller's rows gate only theirs. One global list would make one
    shop's growth campaign everybody's entry requirement.
    """

    __tablename__ = "required_channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: `@name` for a public channel, `-100...` for a private one. Telegram takes
    #: either wherever a chat is named, and two columns would mean every read
    #: choosing between them.
    chat_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Needed for a private channel, whose `@name` cannot be opened. A public
    #: one is reachable from `chat_ref` alone.
    invite_url: Mapped[str | None] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Whose bot this gates. NULL is the platform's own.
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resellers.id", ondelete="CASCADE")
    )

    __table_args__ = (
        Index("ix_required_channels_shop", "reseller_id", "active"),
        # The same channel twice would gate on one requirement and show two
        # buttons for it. NULLs are distinct in Postgres, so each shop has its
        # own namespace and the platform keeps its own.
        Index("uq_required_channels_shop_ref", "reseller_id", "chat_ref", unique=True),
    )
