"""One adopted service per panel account.

The claim checked for an existing row by reading a thousand subscriptions for
the node and scanning them in Python. On a node holding more than that the
answer was "no" without having looked, and the same subscription could be
adopted again and again - by the same customer, or by anybody else who had
seen the link.

The application now asks a real question, but two taps of the same button are
two transactions and both would still find nothing. So the rule is also a
constraint, which is the only thing a race cannot get past.

Scoped to claimed rows (`order_id IS NULL`) on purpose. A purchased
subscription gets a username generated for its order and cannot collide, and a
partial index means this migration cannot fail on data it was never about.

Duplicates already stored are collapsed to the earliest, which is the customer
who actually adopted it first; the later rows are deleted rather than revoked
because a revoked row still shows on the customer's screen as a dead service
they never had. Nothing on any panel is touched - these rows are bookkeeping
about somebody else's account.

Revision ID: 0027_one_claim_per_account
Revises: 0026_reseller_subscription_hosts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_one_claim_per_account"
down_revision = "0026_reseller_subscription_hosts"
branch_labels = None
depends_on = None

INDEX = "ux_subscriptions_claimed_account"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM subscriptions s
            USING subscriptions keep
            WHERE s.order_id IS NULL
              AND keep.order_id IS NULL
              AND s.node_id = keep.node_id
              AND s.remote_username = keep.remote_username
              AND s.node_id IS NOT NULL
              AND (keep.started_at, keep.id) < (s.started_at, s.id)
            """
        )
    )
    op.create_index(
        INDEX,
        "subscriptions",
        ["node_id", "remote_username"],
        unique=True,
        postgresql_where=sa.text("order_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="subscriptions")
