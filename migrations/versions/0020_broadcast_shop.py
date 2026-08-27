"""A broadcast belongs to a shop.

`notify_broadcasts` had no shop, so a reseller composing an announcement would
have written it into the platform's list and sent it from the platform's bot -
to an audience resolved across every customer there is.

NULL is the platform's own, which is every row today.

Revision ID: 0020_broadcast_shop
Revises: 0019_payment_gateways
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_broadcast_shop"
down_revision = "0019_payment_gateways"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notify_broadcasts",
        sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_notify_broadcasts_reseller",
        "notify_broadcasts",
        "resellers",
        ["reseller_id"],
        ["id"],
        # SET NULL: a sent broadcast is a record of something that happened,
        # and it should survive its shop closing.
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notify_broadcasts_reseller_id", "notify_broadcasts", ["reseller_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notify_broadcasts_reseller_id", table_name="notify_broadcasts")
    op.drop_constraint(
        "fk_notify_broadcasts_reseller", "notify_broadcasts", type_="foreignkey"
    )
    op.drop_column("notify_broadcasts", "reseller_id")
