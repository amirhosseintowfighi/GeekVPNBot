"""Who has had the Android app's free trial.

One row per customer who claimed it, keyed by Telegram id like orders. The
trial's orders and subscriptions live in the ordinary tables; this only
remembers the claim. Dropping it on downgrade lets everyone claim again, which
is the honest consequence of removing the rule.

Revision ID: 0034_free_trial_claims
Revises: 0033_app_credentials
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_free_trial_claims"
down_revision = "0033_app_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "free_trial_claims",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("free_trial_claims")
