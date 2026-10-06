"""Let the gateway table hold NowPayments, Plisio, TON and Telegram Stars rows.

The third list a provider lives in (see 0030): without this, saving one of
them raises an IntegrityError and the operator sees a generic failure.

Revision ID: 0040_crypto_and_stars_providers
Revises: 0039_wallet_transfers
"""

from __future__ import annotations

from alembic import op

revision = "0040_crypto_and_stars_providers"
down_revision = "0039_wallet_transfers"
branch_labels = None
depends_on = None

TABLE = "billing_gateway_accounts"
NAME = "ck_gateway_accounts_provider"
CONVENTION_NAME = f"ck_{TABLE}_{NAME}"
ADDED = ("nowpayments", "plisio", "ton", "stars")

OLD = "provider IN ('zarinpal', 'zibal', 'aqayepardakht', 'atlaspay')"
NEW = (
    "provider IN ('zarinpal', 'zibal', 'aqayepardakht', 'atlaspay',"
    " 'nowpayments', 'plisio', 'ton', 'stars')"
)


def _drop_either() -> None:
    for name in (NAME, CONVENTION_NAME):
        op.execute(f'ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS "{name}"')


def upgrade() -> None:
    _drop_either()
    op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT "{NAME}" CHECK ({NEW})')


def downgrade() -> None:
    # Rows for these would fail the old constraint, and without the providers
    # registered they configure a method the code can no longer build.
    names = ", ".join(f"'{name}'" for name in ADDED)
    op.execute(f"DELETE FROM {TABLE} WHERE provider IN ({names})")
    _drop_either()
    op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT "{NAME}" CHECK ({OLD})')
