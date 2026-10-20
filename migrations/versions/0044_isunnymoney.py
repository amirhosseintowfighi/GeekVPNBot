"""iSunnyMoney: its order-id sequence, and a place in the provider list.

The gateway wants an integer order id that is unique and under the 32-bit
limit; the operator asked for it to start at 100001. A sequence gives both,
and never hands the same number to two payments started at once.

Revision ID: 0044_isunnymoney
Revises: 0043_crypto_and_stars_providers
"""

from __future__ import annotations

from alembic import op

revision = "0044_isunnymoney"
down_revision = "0043_crypto_and_stars_providers"
branch_labels = None
depends_on = None

TABLE = "billing_gateway_accounts"
NAME = "ck_gateway_accounts_provider"
CONVENTION_NAME = f"ck_{TABLE}_{NAME}"

OLD = (
    "provider IN ('zarinpal', 'zibal', 'aqayepardakht', 'atlaspay',"
    " 'nowpayments', 'plisio', 'ton', 'stars')"
)
NEW = (
    "provider IN ('zarinpal', 'zibal', 'aqayepardakht', 'atlaspay',"
    " 'nowpayments', 'plisio', 'ton', 'stars', 'isunnymoney')"
)


def _drop_either() -> None:
    for name in (NAME, CONVENTION_NAME):
        op.execute(f'ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS "{name}"')


def upgrade() -> None:
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS isunnymoney_order_seq"
        " START WITH 100001 MINVALUE 100001 MAXVALUE 2147483647 NO CYCLE"
    )
    _drop_either()
    op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT "{NAME}" CHECK ({NEW})')


def downgrade() -> None:
    op.execute(f"DELETE FROM {TABLE} WHERE provider = 'isunnymoney'")
    _drop_either()
    op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT "{NAME}" CHECK ({OLD})')
    op.execute("DROP SEQUENCE IF EXISTS isunnymoney_order_seq")
