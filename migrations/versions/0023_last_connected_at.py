"""When the panel last saw an account connected.

Distinct from `last_used_at`, which moves only when the byte counter grows. A
customer who connects and reaches nothing moves no bytes, and they are exactly
the customer the "still not connected?" message exists for - so deriving the
answer from traffic asked a different question and got a different answer.

Panels report `online_at`. This is where it lands.

NULL for every existing row, and NULL means "we have not been told", not "never
connected". The sweep treats those two differently on purpose: it will not
guess at somebody's silence.

Revision ID: 0023_last_connected_at
Revises: 0022_claimed_subscriptions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_last_connected_at"
down_revision = "0022_claimed_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The sweep reads this column across the whole table every few minutes, and
    # filters on it before anything else narrows the scan.
    op.create_index(
        "ix_subscriptions_last_connected",
        "subscriptions",
        ["last_connected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_last_connected", table_name="subscriptions")
    op.drop_column("subscriptions", "last_connected_at")
