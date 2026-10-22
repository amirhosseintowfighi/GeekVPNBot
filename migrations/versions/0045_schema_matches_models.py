"""Close the last gaps between the migrations and the models.

Two ``created_at`` indexes that ``TimestampMixin`` has always declared were
never created for ``admins`` and ``required_channels``.

The three encrypted columns from ``0004`` go. They were added for a backfill
that was never written, no model maps them, and so no code path has ever put
a value in them; they only made autogenerate propose dropping them on every
run. The upgrade checks rather than assumes: if a database somewhere does hold
data in them, it stops instead of discarding it.

Revision ID: 0045_schema_matches_models
Revises: 0044_isunnymoney
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_schema_matches_models"
down_revision = "0044_isunnymoney"
branch_labels = None
depends_on = None

UNUSED = (
    ("billing_card_accounts", "card_encrypted"),
    ("billing_card_accounts", "card_blind_index"),
    ("billing_payments", "proof_encrypted"),
)


def upgrade() -> None:
    connection = op.get_bind()
    for table, column in UNUSED:
        held = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
        ).scalar_one()
        if held:
            raise RuntimeError(
                f"{table}.{column} holds {held} values; refusing to drop it. "
                "Nothing in the application writes this column, so find out what did."
            )

    op.drop_index("ix_billing_card_accounts_card_blind_index", table_name="billing_card_accounts")
    for table, column in UNUSED:
        op.drop_column(table, column)

    op.create_index("ix_admins_created_at", "admins", ["created_at"])
    op.create_index("ix_required_channels_created_at", "required_channels", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_required_channels_created_at", table_name="required_channels")
    op.drop_index("ix_admins_created_at", table_name="admins")

    op.add_column("billing_payments", sa.Column("proof_encrypted", sa.Text(), nullable=True))
    op.add_column("billing_card_accounts", sa.Column("card_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "billing_card_accounts",
        sa.Column("card_blind_index", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_billing_card_accounts_card_blind_index",
        "billing_card_accounts",
        ["card_blind_index"],
    )
