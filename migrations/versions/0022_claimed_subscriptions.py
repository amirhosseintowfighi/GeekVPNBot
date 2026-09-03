"""A subscription can exist without a sale behind it.

For the customer who bought through support and later wants the bot to manage
the account: there is a real service on a real panel, but no order and no plan
of ours. The alternative was to synthesise a zero-price order for each claim,
which would have written sales that never happened into the revenue figures.

`uq_subscriptions_order` survives untouched. Postgres treats NULLs as distinct
in a unique constraint, so any number of claimed rows coexist while each real
order still buys exactly one service.

Downgrade drops the claimed rows rather than inventing orders for them. That is
destructive and deliberate: they cannot be represented under the old schema at
all, and a fabricated order would be worse than an honest deletion.

Revision ID: 0022_claimed_subscriptions
Revises: 0021_preferred_name
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_claimed_subscriptions"
down_revision = "0021_preferred_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("subscriptions", "order_id", existing_type=sa.String(64), nullable=True)
    op.alter_column(
        "subscriptions", "plan_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True
    )


def downgrade() -> None:
    op.execute("DELETE FROM subscriptions WHERE order_id IS NULL OR plan_id IS NULL")
    op.alter_column("subscriptions", "order_id", existing_type=sa.String(64), nullable=False)
    op.alter_column(
        "subscriptions", "plan_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False
    )
