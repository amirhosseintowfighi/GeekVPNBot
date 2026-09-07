"""A name an operator chose for a payment button.

The label was a constant on each adapter class, so renaming the button a
customer taps meant a deployment. It lives on the account row rather than in
settings because a shop may have several gateways and each wants its own name -
and because a reseller's row is already scoped to their shop, which is exactly
the scope a label needs.

Card and crypto have no row of their own to hang a name on, so those two are
platform settings instead. NULL and empty both mean "use the adapter's own
name", which is what every shop has today.

Revision ID: 0031_gateway_label
Revises: 0030_atlaspay_provider
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_gateway_label"
down_revision = "0030_atlaspay_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_gateway_accounts",
        sa.Column("label_fa", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_gateway_accounts", "label_fa")
