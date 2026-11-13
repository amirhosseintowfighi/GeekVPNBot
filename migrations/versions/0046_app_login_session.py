"""Remember which session an app sign-in issued.

A poll whose answer is lost on the way to the phone can now collect again
while the request lasts, revoking the session it never received. That needs
the request to know which session it issued.

Revision ID: 0046_app_login_session
Revises: 0045_schema_matches_models
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_app_login_session"
down_revision = "0045_schema_matches_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_login_requests",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_login_requests", "session_id")
