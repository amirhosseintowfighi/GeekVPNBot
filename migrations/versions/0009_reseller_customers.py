"""One Telegram account can be a customer of more than one shop.

`users.telegram_id` was globally unique, which was right while this platform
had exactly one storefront. With resellers running their own bots it is wrong
in a way that loses people money: a person who buys from us and later opens a
reseller's bot would be handed *our* account for them - somebody else's shop
showing them a wallet balance and a subscription list from a different seller,
or the insert failing outright.

So a customer now belongs to a shop. NULL means the platform's own bot, which
is every row that exists today.

Two partial indexes rather than one composite unique, because Postgres treats
NULLs as distinct: `UNIQUE (telegram_id, reseller_id)` would happily accept the
same person twice as a platform customer, which is the exact duplicate the old
constraint existed to prevent.

Revision ID: 0009_reseller_customers
Revises: 0008_resellers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_reseller_customers"
down_revision = "0008_resellers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reseller_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_reseller",
        "users",
        "resellers",
        ["reseller_id"],
        ["id"],
        # A closed reseller must not delete the people who bought from them:
        # their subscriptions, orders and tickets all point at these rows.
        ondelete="SET NULL",
    )

    # The old constraint said "one row per Telegram account". The new pair says
    # "one row per Telegram account *per shop*", which is the same rule one
    # level down.
    op.drop_constraint("uq_users_telegram_id", "users", type_="unique")
    op.create_index(
        "uq_users_platform_telegram_id",
        "users",
        ["telegram_id"],
        unique=True,
        postgresql_where=sa.text("reseller_id IS NULL"),
    )
    op.create_index(
        "uq_users_reseller_telegram_id",
        "users",
        ["reseller_id", "telegram_id"],
        unique=True,
        postgresql_where=sa.text("reseller_id IS NOT NULL"),
    )
    # Every screen a reseller opens starts with "my customers".
    op.create_index("ix_users_reseller_id", "users", ["reseller_id"])


def downgrade() -> None:
    # A reseller's customers would violate the restored unique constraint if
    # they share a Telegram id with a platform customer. Removing them is the
    # only way back, and it is why this migration is one nobody should need to
    # reverse after resellers have sold anything.
    op.execute(sa.text("DELETE FROM users WHERE reseller_id IS NOT NULL"))

    op.drop_index("ix_users_reseller_id", table_name="users")
    op.drop_index("uq_users_reseller_telegram_id", table_name="users")
    op.drop_index("uq_users_platform_telegram_id", table_name="users")
    op.create_unique_constraint("uq_users_telegram_id", "users", ["telegram_id"])

    op.drop_constraint("fk_users_reseller", "users", type_="foreignkey")
    op.drop_column("users", "reseller_id")
