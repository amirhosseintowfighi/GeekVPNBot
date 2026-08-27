"""Merchant credentials, per shop.

Shaped like the card and crypto accounts beside it: one row per configured
destination, scoped by `reseller_id`, activated and rotated the same way. A
shop's ways of taking money are one kind of thing, and a third shape here would
be a third thing to scope and audit.

The merchant id is encrypted. It is not a password - it identifies the shop to
the provider - but it is the only thing standing between somebody and a payment
request billed to that shop, and there is no reason to keep it readable.

`provider` is one of a fixed set, checked here rather than only in Python: a
row naming a provider this platform cannot build is a payment button that
raises when a customer presses it.

Revision ID: 0019_payment_gateways
Revises: 0018_reseller_texts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_payment_gateways"
down_revision = "0018_reseller_texts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_gateway_accounts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("merchant_id_encrypted", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('zarinpal', 'zibal', 'aqayepardakht')",
            name="ck_gateway_accounts_provider",
        ),
        sa.ForeignKeyConstraint(
            ["reseller_id"],
            ["resellers.id"],
            # CASCADE like the other two: an account orphaned by a closed
            # reseller would become one of ours and start billing their
            # customers' payments to us.
            ondelete="CASCADE",
            name="fk_gateway_accounts_reseller",
        ),
    )
    op.create_index(
        "ix_billing_gateway_accounts_created_at", "billing_gateway_accounts", ["created_at"]
    )
    op.create_index("ix_billing_gateway_accounts_active", "billing_gateway_accounts", ["active"])
    op.create_index(
        "ix_billing_gateway_accounts_reseller_id", "billing_gateway_accounts", ["reseller_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_gateway_accounts_reseller_id", table_name="billing_gateway_accounts"
    )
    op.drop_index("ix_billing_gateway_accounts_active", table_name="billing_gateway_accounts")
    op.drop_index("ix_billing_gateway_accounts_created_at", table_name="billing_gateway_accounts")
    op.drop_table("billing_gateway_accounts")
