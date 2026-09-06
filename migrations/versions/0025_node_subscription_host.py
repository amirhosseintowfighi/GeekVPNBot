"""The host a node's subscription links are actually served on.

A panel reports links built from the base URL it was configured with, and that
is frequently not the host customers can reach: the API sits on
`panel.doping.games:8443` while subscriptions are served from
`panel2.hostcheap.top`. Handing the customer the panel's own answer gives them
a link to a host that either does not resolve or is not theirs.

NULL means "the same host as the API", which is the common case and stays the
default - an operator who does not have this split never sees the field matter.

Revision ID: 0025_node_subscription_host
Revises: 0024_required_channels
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_node_subscription_host"
down_revision = "0024_required_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("subscription_base_url", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nodes", "subscription_base_url")
