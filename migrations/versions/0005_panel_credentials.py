"""Panel credentials on nodes.

Revision ID: 0005_panel_credentials
Revises: 0004_security_indexes
Create Date: Phase 12.5

Why this migration exists
-------------------------

Phase 3 shipped five panel adapters, a registry and a factory - and nowhere to
store the credentials any of them need. ``nodes`` held ``base_url`` and
``panel_kind`` only, which means ``PanelFactory.build()`` could never be called
with real data and every adapter was unreachable code.

The columns
-----------

``username`` is plaintext. It is not a secret on its own, and keeping it
readable means an operator can identify an account in a panel's own UI without
a decryption round-trip.

``password_encrypted`` uses :class:`EncryptedString` with the context
``node.password``. The context is bound into the AEAD associated data, so a
ciphertext lifted out of ``billing_card_accounts`` cannot be pasted here and
decrypted - which is the usual way envelope encryption fails in practice.

``config_json`` carries the per-adapter extras that differ by panel: Marzban's
``default_inbounds``, Marzneshin's ``service_ids``, PasarGuard's
``default_groups``. It is deliberately opaque JSON rather than a column per
panel, because a column per panel is exactly the "adding a panel edits shipped
code" outcome Phase 3 was built to avoid.

``verify_tls`` gets its own column rather than living in ``config_json`` because
turning it off is a security decision an operator must be able to audit with a
single query across every node.

Nullability
-----------

``password_encrypted`` is nullable. Existing rows have no credentials and there
is nothing to backfill them with; the provisioning path treats a node without
credentials as unusable and says so, which is louder and safer than a NOT NULL
that would refuse to run this migration on a live database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from geekvpn.infrastructure.persistence.types import EncryptedString

revision = "0005_panel_credentials"
down_revision = "0004_security_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("username", sa.String(128), nullable=False, server_default=""),
    )
    op.add_column(
        "nodes",
        sa.Column("password_encrypted", EncryptedString("node.password"), nullable=True),
    )
    op.add_column(
        "nodes",
        sa.Column("verify_tls", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "nodes",
        sa.Column("config_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "nodes",
        sa.Column(
            "timeout_seconds",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="15.00",
        ),
    )

    # A node that is online and accepting customers but has no password is a
    # provisioning failure waiting to happen. The constraint makes it a write
    # error at configuration time instead.
    op.create_check_constraint(
        "nodes_online_requires_credentials",
        "nodes",
        "state <> 'online' OR accepting_new IS FALSE OR password_encrypted IS NOT NULL",
    )

    # The provisioning selector reads exactly this shape: sellable nodes,
    # cheapest first. Partial, because retired and offline nodes accumulate and
    # are never candidates.
    op.create_index(
        "ix_nodes_sellable",
        "nodes",
        ["sort_order", "id"],
        postgresql_where=sa.text("state = 'online' AND accepting_new IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_nodes_sellable", table_name="nodes")
    op.drop_constraint("nodes_online_requires_credentials", "nodes", type_="check")
    for column in (
        "timeout_seconds",
        "config_json",
        "verify_tls",
        "password_encrypted",
        "username",
    ):
        op.drop_column("nodes", column)
