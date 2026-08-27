"""A reseller rewriting the words their own bot says.

Overrides rather than copies. A reseller stores only the screens they have
changed, and everything else follows the platform's copy - so improving a
message improves it in every shop that has not deliberately taken it over,
which is the opposite of seeding each new reseller with a frozen snapshot of
whatever the text file said the day they signed up.

The key is the constant's name in `presentation/bot/ui/text.py`. That couples
this table to a Python module, which is a real cost and the honest one: the
alternative is inventing a second vocabulary for the same screens and keeping
the two in step by hand.

Revision ID: 0018_reseller_texts
Revises: 0017_crypto_accounts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_reseller_texts"
down_revision = "0017_crypto_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reseller_texts",
        sa.Column(
            "reseller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resellers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        #: The constant's name, e.g. `WELCOME_NEW`.
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("body_fa", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("reseller_texts")
