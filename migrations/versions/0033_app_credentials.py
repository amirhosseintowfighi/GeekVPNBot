"""Usernames and passwords for the Android app, set from the bot.

One row per customer who chose to set one; most never will. Only an Argon2id
hash is stored. Nothing references the table, and a customer whose row is
dropped simply signs in through Telegram again, so the downgrade drops it.

Revision ID: 0033_app_credentials
Revises: 0032_app_login_requests
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_app_credentials"
down_revision = "0032_app_login_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_credentials",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_app_credentials_username"),
        sa.CheckConstraint("username = lower(username)", name="app_credentials_username_lower"),
    )


def downgrade() -> None:
    op.drop_table("app_credentials")
