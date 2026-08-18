"""Widen alembic_version.version_num to 64 characters.

Alembic creates ``alembic_version.version_num`` as ``VARCHAR(32)`` unless told
otherwise. Two revision ids in this tree are longer than that -
``0003_billing_support_notifications_provisioning`` is 47 characters - so
stamping them failed with a value-too-long error against a column nobody in
this repository had written.

``migrations/env.py`` now passes ``version_table_column_length=64``, which
covers every database created from here on. This migration is for one created
before that: the column already exists at 32 and only an ALTER can widen it.

Deliberately no-ops when the column is already wide enough, so it is safe to
run against a database that was created after the env.py fix.

Revision ID: 0006_widen_version_column
Revises: 0005_panel_credentials
"""

from __future__ import annotations

from alembic import op

revision = "0006_widen_version_column"
down_revision = "0005_panel_credentials"
branch_labels = None
depends_on = None

#: The length env.py configures. Kept in one place so the two cannot drift.
TARGET_LENGTH = 64


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'alembic_version'
                  AND column_name = 'version_num'
                  AND character_maximum_length < {TARGET_LENGTH}
            ) THEN
                ALTER TABLE alembic_version
                    ALTER COLUMN version_num TYPE VARCHAR({TARGET_LENGTH});
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Deliberately does nothing.

    Narrowing the column back to 32 would truncate the very rows that record
    which migrations have run, and this revision's own id is 24 characters, so
    the downgrade would be writing a value the narrowed column could still
    hold while destroying the history of the ones it could not.
    """
