"""A reseller's prefix and suffix for their customers' config names.

Revision ID: 0037_reseller_config_names
Revises: 0036_broadcast_audiences
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_reseller_config_names"
down_revision = "0036_broadcast_audiences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resellers", sa.Column("config_prefix", sa.String(10), nullable=True))
    op.add_column("resellers", sa.Column("config_suffix", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("resellers", "config_suffix")
    op.drop_column("resellers", "config_prefix")
