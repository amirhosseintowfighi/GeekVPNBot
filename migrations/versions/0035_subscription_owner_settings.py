"""What a customer may decide about their own service.

``auto_renew`` is the customer's consent to be charged from their wallet
before the service runs out; it defaults to false for every existing row,
because nobody has agreed to anything yet. ``display_name`` is a label of
their choosing, shown in the bot and never sent to the panel.

Revision ID: 0035_subscription_owner_settings
Revises: 0034_free_trial_claims
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_subscription_owner_settings"
down_revision = "0034_free_trial_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("subscriptions", sa.Column("display_name", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "display_name")
    op.drop_column("subscriptions", "auto_renew")
