"""Resellers: their account, prices, panels and credit.

Four new tables and one new column. Nothing existing is renamed or dropped, so
this is safe under the blue/green rule that both versions of the code run
against the new schema for a moment: the old code simply does not know these
tables are there.

The column on `subscriptions` is the exception worth reading twice. It is
nullable with no default, because every subscription that already exists was
sold by the platform rather than by a reseller, and NULL is the honest way to
say so - a default of any particular reseller would be a lie about history.

Revision ID: 0008_resellers
Revises: 0007_subscription_order_unique
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_resellers"
down_revision = "0007_subscription_order_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resellers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admins.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name_fa", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("discount_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=True),
        sa.Column("bot_username", sa.String(64), nullable=True, unique=True),
        sa.Column("contact_fa", sa.String(256), nullable=True),
        sa.Column("note_fa", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'closed')", name="resellers_status"
        ),
        sa.CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 90", name="resellers_discount"
        ),
        # No non-negative constraint on the balance. It may go under through an
        # operator settlement, and the consequence is that the reseller's
        # customers are suspended until it is positive again - which is the
        # credit limit this platform enforces, in place of a number nobody
        # would keep up to date.
    )
    op.create_index("ix_resellers_status", "resellers", ["status"])

    op.create_table(
        "reseller_plan_prices",
        sa.Column(
            "reseller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("catalog_plans.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Two prices, set by two different people. `price` is what the platform
        # charges this reseller, set by an operator; `retail_price` is what the
        # reseller charges their own customer, set by the reseller. Either may
        # be NULL, meaning "not decided" - the percentage applies for one, the
        # platform's list price for the other.
        sa.Column("price", sa.BigInteger(), nullable=True),
        sa.Column("retail_price", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "price IS NULL OR price >= 0", name="reseller_plan_prices_non_negative"
        ),
        sa.CheckConstraint(
            "retail_price IS NULL OR retail_price >= 0",
            name="reseller_plan_prices_retail_non_negative",
        ),
    )

    op.create_table(
        "reseller_nodes",
        sa.Column(
            "reseller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "node_id",
            sa.String(64),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "reseller_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "reseller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("description_fa", sa.String(256), nullable=False, server_default=""),
        sa.Column("reference", sa.String(64), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", name="reseller_ledger_id_unique"),
    )
    op.create_index("ix_reseller_ledger_kind", "reseller_ledger", ["kind"])
    op.create_index("ix_reseller_ledger_reference", "reseller_ledger", ["reference"])
    op.create_index(
        "ix_reseller_ledger_reseller_time", "reseller_ledger", ["reseller_id", "occurred_at"]
    )

    # Which reseller sold this, if any. NULL means the platform sold it
    # directly, which is every row that exists today.
    op.add_column(
        "subscriptions",
        sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_subscriptions_reseller",
        "subscriptions",
        "resellers",
        ["reseller_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # The reseller's own list of what they have sold, which is the first screen
    # they open and would otherwise scan the whole table.
    op.create_index("ix_subscriptions_reseller", "subscriptions", ["reseller_id"])

    # Why a suspended subscription is suspended. The reason previously existed
    # only on the event, so nothing could tell two suspensions apart afterwards
    # - and the difference decides whether paying a debt brings a service back.
    op.add_column(
        "subscriptions", sa.Column("suspend_reason_fa", sa.String(512), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "suspend_reason_fa")
    op.drop_index("ix_subscriptions_reseller", table_name="subscriptions")
    op.drop_constraint("fk_subscriptions_reseller", "subscriptions", type_="foreignkey")
    op.drop_column("subscriptions", "reseller_id")

    op.drop_index("ix_reseller_ledger_reseller_time", table_name="reseller_ledger")
    op.drop_index("ix_reseller_ledger_reference", table_name="reseller_ledger")
    op.drop_index("ix_reseller_ledger_kind", table_name="reseller_ledger")
    op.drop_table("reseller_ledger")
    op.drop_table("reseller_nodes")
    op.drop_table("reseller_plan_prices")
    op.drop_index("ix_resellers_status", table_name="resellers")
    op.drop_table("resellers")
