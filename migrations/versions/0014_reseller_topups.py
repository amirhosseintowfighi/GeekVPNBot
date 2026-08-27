"""A reseller asking to have their credit topped up.

Their own table rather than the wallet's. A reseller's credit is not a customer
wallet - it has no gateway, no cashback and no refund policy - and the one
thing this needs that the wallet flow does not have is an operator deciding
whether the money actually arrived, which is the whole transaction.

Deliberately thin: an amount, a note, and a decision. The money itself moves
through `ResellerService.adjust_credit`, so the balance still only changes in
one place and still writes a ledger row on the way.

Revision ID: 0014_reseller_topups
Revises: 0013_reseller_timestamps
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_reseller_topups"
down_revision = "0013_reseller_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reseller_topups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reseller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        #: Whatever the reseller wants to identify their transfer by - a
        #: reference number, the last digits of the card they sent from.
        sa.Column("note_fa", sa.String(256), nullable=True),
        #: The receipt image, as a Telegram file id when it came from a bot.
        sa.Column("receipt_file_id", sa.String(256), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_fa", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_reseller_topups_amount"),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')",
            name="ck_reseller_topups_state",
        ),
    )
    op.create_index("ix_reseller_topups_created_at", "reseller_topups", ["created_at"])
    op.create_index("ix_reseller_topups_state", "reseller_topups", ["state"])
    op.create_index(
        "ix_reseller_topups_reseller_id", "reseller_topups", ["reseller_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_reseller_topups_reseller_id", table_name="reseller_topups")
    op.drop_index("ix_reseller_topups_state", table_name="reseller_topups")
    op.drop_index("ix_reseller_topups_created_at", table_name="reseller_topups")
    op.drop_table("reseller_topups")
