"""Where an administrator's recovery codes live.

`infrastructure/security/recovery_codes.py` has been complete since it was
written - generation, scrypt hashing, single use, the low-codes nudge - and
nothing called any of it. There was no column to store a code in and no route
to spend one, so an operator who lost their TOTP device had exactly one way
back in: an UPDATE against production by whoever holds the database password.
That is both an outage and the least auditable privilege escalation in the
system, which is the thing the module was written to remove.

Hashes only, and scrypt rather than a plain digest: these are short,
human-typed secrets that live for months on a printed page, so a stolen table
must not be brute-forceable at GPU speed.

Empty for every existing admin. Nobody is issued codes by a migration - they
are shown exactly once, to the person who asked for them.

Revision ID: 0029_admin_recovery_codes
Revises: 0028_backfill_referral_edges
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_admin_recovery_codes"
down_revision = "0028_backfill_referral_edges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column(
            "recovery_code_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("admins", "recovery_code_hashes")
