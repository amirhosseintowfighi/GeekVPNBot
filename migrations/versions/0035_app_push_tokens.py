"""Firebase Cloud Messaging tokens of the Android app.

One row per installed app, keyed by the token and owned by a Telegram id, so a
support answer can reach the app as well as the bot. Dropping it on downgrade
only means the apps register again.

Revision ID: 0035_app_push_tokens
Revises: 0034_free_trial_claims
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_app_push_tokens"
down_revision = "0034_free_trial_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_push_tokens",
        sa.Column("token", sa.String(length=512), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_app_push_tokens_telegram_id", "app_push_tokens", ["telegram_id"])


def downgrade() -> None:
    op.drop_index("ix_app_push_tokens_telegram_id", table_name="app_push_tokens")
    op.drop_table("app_push_tokens")
