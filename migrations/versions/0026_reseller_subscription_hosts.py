"""A reseller's own domain for the links their customers receive.

The node already declares where its subscription links are really served
(0025). A reseller sells from the same panel but under their own name, and
their customers must not be handed a link on our domain - so the host is
overridable per shop, per node.

A map rather than one host: a reseller selling from three panels needs three
domains, because a subscription token is only meaningful to the panel that
minted it. Keyed by node id, empty meaning "whatever the node says", which is
what every existing reseller gets.

Revision ID: 0026_reseller_subscription_hosts
Revises: 0025_node_subscription_host
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_reseller_subscription_hosts"
down_revision = "0025_node_subscription_host"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resellers",
        sa.Column(
            "subscription_hosts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("resellers", "subscription_hosts")
