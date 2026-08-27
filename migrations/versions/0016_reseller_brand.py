"""A reseller's bot says a reseller's name.

Their bot greeted their customers with "welcome to the Geek VPN family" -
our brand, under a name the customer believes belongs to somebody else. It is
the first message anyone sees in that bot, and it undoes the whole point of a
reseller having one.

NULL falls back to the platform's own name, which is every row today and stays
correct for the platform's own bot.

Revision ID: 0016_reseller_brand
Revises: 0015_tenant_columns
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_reseller_brand"
down_revision = "0015_tenant_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resellers", sa.Column("brand_fa", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("resellers", "brand_fa")
