"""Sign-in requests from the Android app, approved in the bot.

The app has no Telegram signature of its own, so it asks for a request, the
customer opens a deep link and taps "approve" in the bot, and the app collects
its tokens with a poll token only it holds. See `AppLinkLogin`.

Only hashes of the code and the poll token are stored. Rows are short-lived
(five minutes of use) and nothing references them, so the downgrade simply
drops the table.

Revision ID: 0032_app_login_requests
Revises: 0031_gateway_label
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_app_login_requests"
down_revision = "0031_gateway_label"
branch_labels = None
depends_on = None

_STATUSES = "'pending', 'approved', 'denied', 'expired', 'consumed'"


def upgrade() -> None:
    op.create_table(
        "app_login_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("poll_token_hash", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="app_login_requests_status"),
        sa.UniqueConstraint("code_hash", name="uq_app_login_requests_code_hash"),
        sa.UniqueConstraint("poll_token_hash", name="uq_app_login_requests_poll_token_hash"),
    )
    op.create_index("ix_app_login_requests_expires_at", "app_login_requests", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_app_login_requests_expires_at", table_name="app_login_requests")
    op.drop_table("app_login_requests")
