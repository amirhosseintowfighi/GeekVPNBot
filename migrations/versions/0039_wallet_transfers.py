"""Wallet-to-wallet transfers: two more ledger kinds.

The column is guarded by a check constraint listing every kind, so without
this every transfer fails on insert. 0003's constraint name went through the
naming convention twice and was truncated to a hash, so it is found by what it
checks rather than by name.

Revision ID: 0039_wallet_transfers
Revises: 0038_reseller_trial_limit
"""

from __future__ import annotations

from alembic import op

revision = "0039_wallet_transfers"
down_revision = "0038_reseller_trial_limit"
branch_labels = None
depends_on = None

NAME = "ck_billing_wallet_entries_billing_wallet_kind"
OLD_KINDS = "'topup', 'purchase', 'refund', 'cashback', 'referral_reward', 'adjustment', 'overpayment'"
NEW_KINDS = OLD_KINDS + ", 'transfer_out', 'transfer_in'"

DROP_KIND_CHECK = """
DO $$
DECLARE found text;
BEGIN
    FOR found IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'billing_wallet_entries'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%kind%'
    LOOP
        EXECUTE format('ALTER TABLE billing_wallet_entries DROP CONSTRAINT %I', found);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(DROP_KIND_CHECK)
    op.create_check_constraint(op.f(NAME), "billing_wallet_entries", f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    # A transfer is money that really moved; relabelled as an adjustment rather
    # than deleted, so every balance still adds up.
    op.execute(
        "UPDATE billing_wallet_entries SET kind = 'adjustment' "
        "WHERE kind IN ('transfer_out', 'transfer_in')"
    )
    op.execute(DROP_KIND_CHECK)
    op.create_check_constraint(op.f(NAME), "billing_wallet_entries", f"kind IN ({OLD_KINDS})")
