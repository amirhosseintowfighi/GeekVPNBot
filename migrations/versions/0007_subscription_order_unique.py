"""One order may buy exactly one subscription.

``subscriptions.order_id`` was indexed but not unique, and ``provision`` reads
the order without locking it. Two concurrent provisions of the same order -
the retry sweep firing while a manual retry-provision is in flight, say - both
found no existing subscription and both inserted one. The customer ends up with
two accounts on two nodes for one payment, and ``get_by_order`` can only ever
show one of them, so the other is invisible and never revoked.

The constraint is the half that holds under concurrency; the row lock in
``provision`` is the half that turns a violation into a wait.

Revision ID: 0007_subscription_order_unique
Revises: 0006_widen_version_column
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_subscription_order_unique"
down_revision = "0006_widen_version_column"
branch_labels = None
depends_on = None

CONSTRAINT = "uq_subscriptions_order"


def upgrade() -> None:
    # Fail loudly rather than silently dropping one of a duplicated pair: which
    # of two live accounts to revoke is an operator's decision, not a
    # migration's.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT order_id FROM subscriptions "
                "GROUP BY order_id HAVING count(*) > 1"
            )
        )
        .fetchall()
    )
    if duplicates:
        raise RuntimeError(
            "Cannot add uq_subscriptions_order: these orders already have more "
            f"than one subscription: {[row[0] for row in duplicates]}. "
            "Revoke the surplus accounts on their panels first."
        )

    op.create_unique_constraint(CONSTRAINT, "subscriptions", ["order_id"])


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "subscriptions", type_="unique")
