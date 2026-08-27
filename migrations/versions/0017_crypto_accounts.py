"""Somewhere to put a crypto address, for us and for each reseller.

`CryptoTransferGateway` has existed since the payment layer was written, with
tests, and nothing in this project ever constructed it - so the bot has always
offered "pay with crypto" and always answered the customer with a generic
apology when they tapped it. The gateway registry had nowhere to read an
address from.

Shaped like `billing_card_accounts` on purpose, down to the `reseller_id` and
the sort order. A shop's payment destinations are the same kind of thing
whichever chain they are on, and a second shape here would be a second thing to
scope, rotate and audit.

Revision ID: 0017_crypto_accounts
Revises: 0016_reseller_brand
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_crypto_accounts"
down_revision = "0016_reseller_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_crypto_accounts",
        sa.Column("id", sa.String(64), primary_key=True),
        #: Public by definition - it is what a customer sends money to - so it
        #: is stored readable, unlike a panel password or a bot token.
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False, server_default="USDT"),
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
        sa.ForeignKeyConstraint(
            ["reseller_id"],
            ["resellers.id"],
            # CASCADE, like cards: an address orphaned by a closed reseller
            # would become one of *ours* and start collecting their customers'
            # transfers.
            ondelete="CASCADE",
            name="fk_crypto_accounts_reseller",
        ),
        sa.UniqueConstraint("address", "network", name="uq_crypto_address_network"),
    )
    op.create_index(
        "ix_billing_crypto_accounts_created_at", "billing_crypto_accounts", ["created_at"]
    )
    op.create_index("ix_billing_crypto_accounts_active", "billing_crypto_accounts", ["active"])
    op.create_index(
        "ix_billing_crypto_accounts_reseller_id", "billing_crypto_accounts", ["reseller_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_billing_crypto_accounts_reseller_id", table_name="billing_crypto_accounts")
    op.drop_index("ix_billing_crypto_accounts_active", table_name="billing_crypto_accounts")
    op.drop_index("ix_billing_crypto_accounts_created_at", table_name="billing_crypto_accounts")
    op.drop_table("billing_crypto_accounts")
