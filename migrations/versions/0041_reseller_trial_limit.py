"""How many test accounts a reseller may hand out.

Revision ID: 0041_reseller_trial_limit
Revises: 0040_reseller_config_names
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_reseller_trial_limit"
down_revision = "0040_reseller_config_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no default: NULL is "no limit", which is what every
    # existing reseller had.
    op.add_column("resellers", sa.Column("trial_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("resellers", "trial_limit")
