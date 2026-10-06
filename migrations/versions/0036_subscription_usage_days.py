"""Daily traffic readings per subscription, for the app's usage chart.

The last panel reading of each Tehran day; a day's traffic is the difference
from the previous day. Dropping it on downgrade only loses the history.

Revision ID: 0036_subscription_usage_days
Revises: 0035_app_push_tokens
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_subscription_usage_days"
down_revision = "0035_app_push_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_usage_days",
        sa.Column(
            "subscription_id",
            sa.String(length=64),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("used_mib", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("subscription_usage_days")
