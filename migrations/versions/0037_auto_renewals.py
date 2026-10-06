"""Auto-renew from the wallet, per subscription (the Android app's switch).

Revision ID: 0037_auto_renewals
Revises: 0036_subscription_usage_days
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_auto_renewals"
down_revision = "0036_subscription_usage_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_renewals",
        sa.Column(
            "subscription_id",
            sa.String(length=64),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_auto_renewals_telegram_id", "auto_renewals", ["telegram_id"])


def downgrade() -> None:
    op.drop_index("ix_auto_renewals_telegram_id", table_name="auto_renewals")
    op.drop_table("auto_renewals")
