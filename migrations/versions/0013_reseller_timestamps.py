"""The reseller tables had no default for their own timestamps.

`TimestampMixin` declares `created_at` and `updated_at` with
`server_default=func.now()`, which means the application never sends them - it
relies on the database to fill them in. Both reseller tables were created
`NOT NULL` with no default, so every insert was rejected outright.

That is why creating a reseller failed in the panel *and* why submitting an
application failed in the bot: one cause, two doors, and an error message in
each that could say nothing more useful than "something went wrong".

The missing `created_at` indexes come from the same mismatch. The mixin marks
the column indexed and the migrations did not create it, so the index existed
in the model and nowhere a query could use it.

Revision ID: 0013_reseller_timestamps
Revises: 0012_reseller_applications
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_reseller_timestamps"
down_revision = "0012_reseller_applications"
branch_labels = None
depends_on = None

TABLES = ("resellers", "reseller_applications")


def upgrade() -> None:
    for table in TABLES:
        for column in ("created_at", "updated_at"):
            op.alter_column(
                table,
                column,
                server_default=sa.text("now()"),
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
            )
        # `TimestampMixin` marks created_at indexed; the creating migrations
        # did not, so the index existed in the model and nowhere else.
        op.create_index(f"ix_{table}_created_at", table, ["created_at"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_created_at", table_name=table)
        for column in ("created_at", "updated_at"):
            op.alter_column(
                table,
                column,
                server_default=None,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
            )
