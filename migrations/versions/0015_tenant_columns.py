"""Money, orders and tickets belong to a shop too.

`0009` gave `users` a `reseller_id` and a unique index per shop, which made a
Telegram account a separate *person* in each shop. It did not go far enough:
every table underneath is keyed by the raw Telegram id, not by that person - so
one wallet, one order history and one ticket list were shared across every shop
the same account appeared in.

That is not a subtle inconsistency. Starting a reseller's bot showed the
platform owner their own wallet balance, because it was literally the same
wallet row.

The Telegram id has to stay: it is what a notification is delivered to, and a
synthetic key would break every send. So the shop travels beside it, and the
queries filter on both. NULL is the platform's own shop, which is every row
that exists today.

The indexes are on `(reseller_id, user_id)` rather than `reseller_id` alone,
because no query here ever wants "everything in a shop" - they want one
person's rows in one shop, which is the pair.

Revision ID: 0015_tenant_columns
Revises: 0014_reseller_topups
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_tenant_columns"
down_revision = "0014_reseller_topups"
branch_labels = None
depends_on = None

#: Every table keyed by a raw Telegram id.
TABLES = (
    "billing_invoices",
    "billing_payments",
    "billing_refunds",
    "billing_wallet_entries",
    "billing_receipt_digests",
    "orders",
    "subscriptions",
    "support_tickets",
    "notify_notifications",
    "notify_preferences",
    "funnel_events",
)


def upgrade() -> None:
    for table in TABLES:
        # `subscriptions` already has one, from 0008: it records which reseller
        # *sold* the service, which is the same fact this column carries
        # everywhere else. Adding a second would be two answers to one
        # question.
        if table == "subscriptions":
            continue
        op.add_column(
            table,
            sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_reseller",
            table,
            "resellers",
            ["reseller_id"],
            ["id"],
            # Closing a reseller must not delete the money their customers
            # spent. The rows survive, orphaned and readable, which is what an
            # accountant needs and what a cascade would destroy.
            ondelete="SET NULL",
        )
        op.create_index(
            f"ix_{table}_shop", table, ["reseller_id", "user_id"]
        )


def downgrade() -> None:
    for table in TABLES:
        if table == "subscriptions":
            continue
        op.drop_index(f"ix_{table}_shop", table_name=table)
        op.drop_constraint(f"fk_{table}_reseller", table, type_="foreignkey")
        op.drop_column(table, "reseller_id")
