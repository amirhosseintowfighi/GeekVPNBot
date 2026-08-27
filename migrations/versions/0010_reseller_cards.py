"""A destination card belongs to a shop.

A reseller's customer transfers to the *reseller's* card. The reseller has
already bought the package from us out of their credit, so money arriving on
our card for it would be charging twice for one service - and silently, which
is the part that makes it worth a column rather than a convention.

NULL is the platform's own card, which is every row that exists today.

CASCADE rather than SET NULL, unlike everywhere else resellers are referenced.
A card orphaned by a closed reseller would become one of *ours* the moment its
owner disappeared, and start collecting their customers' transfers.

Revision ID: 0010_reseller_cards
Revises: 0009_reseller_customers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_reseller_cards"
down_revision = "0009_reseller_customers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_card_accounts",
        sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_card_accounts_reseller",
        "billing_card_accounts",
        "resellers",
        ["reseller_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_billing_card_accounts_reseller_id", "billing_card_accounts", ["reseller_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_card_accounts_reseller_id", table_name="billing_card_accounts"
    )
    op.drop_constraint(
        "fk_card_accounts_reseller", "billing_card_accounts", type_="foreignkey"
    )
    op.drop_column("billing_card_accounts", "reseller_id")
