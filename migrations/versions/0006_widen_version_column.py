"""Widen alembic_version.version_num to 64 characters.

Alembic creates ``alembic_version.version_num`` as ``VARCHAR(32)`` and there is
no option to change it: the length is hardcoded in
``DefaultImpl.version_table_impl``. Two revision ids here were once longer than
that, so stamping them failed with a value-too-long error against a column
nobody in this repository had written.

The actual fix is that no revision id exceeds 32 characters any more, asserted
by ``test_no_revision_id_exceeds_the_column_alembic_actually_creates``. This
migration is kept as headroom for a database that reaches it, and because
removing it would re-chain 0007 for no gain. It is not what makes a fresh
install work - nothing can widen the column before Alembic first writes to it.

Deliberately no-ops when the column is already wide enough.

Revision ID: 0006_widen_version_column
Revises: 0005_panel_credentials
"""

from __future__ import annotations

from alembic import op

revision = "0006_widen_version_column"
down_revision = "0005_panel_credentials"
branch_labels = None
depends_on = None

#: Headroom over Alembic's hardcoded 32, not a value anything else depends on.
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
