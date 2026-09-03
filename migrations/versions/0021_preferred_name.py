"""The name a customer chose for themselves.

`display_name` was built from `first_name`, and `first_name` is overwritten from
the Telegram payload on every single authentication - so a customer who asked to
be called something kept that name only until their next /start, when it
silently reverted to whatever their Telegram account says.

Nullable, and NULL for every row that exists: nobody has chosen a name under a
schema that could not hold one. The name reverts to the Telegram one when this
is empty, which is the behaviour everybody has today.

Revision ID: 0021_preferred_name
Revises: 0020_broadcast_shop
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_preferred_name"
down_revision = "0020_broadcast_shop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferred_name")
