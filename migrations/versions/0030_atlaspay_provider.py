"""Let the gateway table hold an AtlasPay row.

Adding a provider means touching three lists, and only two of them are Python:
the builder registry, the request schema, and a CHECK constraint written into
migration 0019. The first two were updated and this one was not, so saving an
AtlasPay account raised an IntegrityError nothing caught - a 500, and on screen
the generic "something went wrong", which names none of it.

The constraint stays rather than being dropped for good. It is the only thing
that stops a typo in a provider name becoming a row that registers no gateway:
the account would read as configured in the panel and the payment method would
simply never appear.

Dropped by both names it might carry. `op.create_table` in 0019 built the
constraint against Alembic's own metadata, which has no naming convention, so
the database almost certainly holds `ck_gateway_accounts_provider` - while the
model's metadata applies the convention and calls the same thing
`ck_billing_gateway_accounts_ck_gateway_accounts_provider`. `IF EXISTS` twice
is shorter than being certain which environment has which.

Revision ID: 0030_atlaspay_provider
Revises: 0029_admin_recovery_codes
"""

from __future__ import annotations

from alembic import op

revision = "0030_atlaspay_provider"
down_revision = "0029_admin_recovery_codes"
branch_labels = None
depends_on = None

TABLE = "billing_gateway_accounts"
NAME = "ck_gateway_accounts_provider"
CONVENTION_NAME = f"ck_{TABLE}_{NAME}"

OLD = "provider IN ('zarinpal', 'zibal', 'aqayepardakht')"
NEW = "provider IN ('zarinpal', 'zibal', 'aqayepardakht', 'atlaspay')"


def _drop_either() -> None:
    for name in (NAME, CONVENTION_NAME):
        op.execute(f'ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS "{name}"')


def upgrade() -> None:
    _drop_either()
    op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT "{NAME}" CHECK ({NEW})')


def downgrade() -> None:
    # Any AtlasPay rows would fail the old constraint, so they go first. There
    # is nothing to preserve: without the provider registered they configure a
    # payment method the code can no longer build.
    op.execute(f"DELETE FROM {TABLE} WHERE provider = 'atlaspay'")
    _drop_either()
    op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT "{NAME}" CHECK ({OLD})')
