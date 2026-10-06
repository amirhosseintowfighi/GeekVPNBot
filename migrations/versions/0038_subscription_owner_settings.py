"""What a customer may decide about their own service.

``auto_renew`` is the customer's consent to be charged from their wallet
before the service runs out; it defaults to false for every existing row,
because nobody has agreed to anything yet - except where they already did,
in the Android app's `auto_renewals` (0037). Those are copied over: the
column is now the one switch both the app and the bot flip, and a consent
given in the app must not be lost by the merge of the two. ``display_name`` is a label of
their choosing, shown in the bot and never sent to the panel.

Revision ID: 0038_subscription_owner_settings
Revises: 0037_auto_renewals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_subscription_owner_settings"
down_revision = "0037_auto_renewals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("subscriptions", sa.Column("display_name", sa.String(32), nullable=True))
    op.execute(
        "UPDATE subscriptions SET auto_renew = true "
        "WHERE id IN (SELECT subscription_id FROM auto_renewals WHERE enabled)"
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "display_name")
    op.drop_column("subscriptions", "auto_renew")
