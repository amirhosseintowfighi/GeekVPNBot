"""Asking to become a reseller, and setting a password without being sent one.

Two things, in one revision because they are two halves of one flow: somebody
applies from the bot, an operator approves, and the approval has to leave them
able to sign in.

`reseller_applications` is its own table rather than a ticket. A ticket is a
conversation that ends; this is a record with a decision attached, and the
partial unique index below is the reason it cannot be a conversation - one
pending application per person, enforced by the database rather than by
whichever handler remembered to check.

The columns on `admins` are how an approved reseller reaches the panel without
a password travelling through Telegram. A one-time token is mailed to nobody:
it goes into a link they tap, they choose their own password, and the hash is
cleared. Only a hash is stored, for the same reason passwords are hashed - a
database dump must not hand somebody else's account over.

Revision ID: 0012_reseller_applications
Revises: 0011_reseller_role
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_reseller_applications"
down_revision = "0011_reseller_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reseller_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name_fa", sa.String(128), nullable=False),
        sa.Column("contact_fa", sa.String(256), nullable=True),
        sa.Column("note_fa", sa.String(512), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason_fa", sa.String(512), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        # The reseller this became, once approved. Null while pending, and null
        # forever on a rejection.
        sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')",
            name="ck_reseller_applications_state",
        ),
        sa.ForeignKeyConstraint(
            ["reseller_id"], ["resellers.id"], ondelete="SET NULL",
            name="fk_reseller_applications_reseller",
        ),
    )
    # One pending application per person, in the database rather than in
    # whichever handler remembered to check. Somebody who taps the button twice
    # while waiting must not create a second row for an operator to decide
    # twice.
    op.create_index(
        "uq_reseller_applications_pending",
        "reseller_applications",
        ["telegram_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index(
        "ix_reseller_applications_state", "reseller_applications", ["state"]
    )

    # Setting a panel password without one ever being sent.
    op.add_column("admins", sa.Column("setup_token_hash", sa.String(128), nullable=True))
    op.add_column(
        "admins",
        sa.Column("setup_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admins", "setup_token_expires_at")
    op.drop_column("admins", "setup_token_hash")
    op.drop_index("ix_reseller_applications_state", table_name="reseller_applications")
    op.drop_index("uq_reseller_applications_pending", table_name="reseller_applications")
    op.drop_table("reseller_applications")
