"""Channels a customer must join before the bot will serve them.

Per shop, like every other customer-facing setting: NULL is the platform's own
bot, and a reseller's rows gate only their bot. A single global list would make
one shop's growth campaign everybody's entry requirement.

CASCADE on the reseller, unlike subscriptions: closing a shop should take its
join requirements with it, because they only ever meant anything inside that
shop's bot.

Revision ID: 0024_required_channels
Revises: 0023_last_connected_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_required_channels"
down_revision = "0023_last_connected_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "required_channels",
        sa.Column("id", sa.String(length=64), primary_key=True),
        # `@name` for a public channel, `-100...` for a private one. Stored as
        # text because Telegram accepts either wherever a chat is named, and
        # splitting them into two columns would mean every read choosing.
        sa.Column("chat_ref", sa.String(length=128), nullable=False),
        sa.Column("title_fa", sa.String(length=128), nullable=False),
        # Needed for a private channel, whose `@name` cannot be opened. Public
        # ones are reachable from `chat_ref` alone.
        sa.Column("invite_url", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reseller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_required_channels_shop", "required_channels", ["reseller_id", "active"]
    )
    # The same channel twice would gate a customer on one requirement while
    # showing them two buttons for it. Postgres treats NULLs as distinct, so
    # each shop gets its own namespace and the platform keeps its own.
    op.create_index(
        "uq_required_channels_shop_ref",
        "required_channels",
        ["reseller_id", "chat_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_required_channels_shop_ref", table_name="required_channels")
    op.drop_index("ix_required_channels_shop", table_name="required_channels")
    op.drop_table("required_channels")
