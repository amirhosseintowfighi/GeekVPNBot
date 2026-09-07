"""Build the referral edges that were never written.

`referrals` had five readers and no writer. The deep link worked - it recorded
`referred_by_code` on the invitee - but nothing joined the two accounts, so the
customer's own referral screen, the operator's programme report and three
analytics queries all counted rows that did not exist and answered "nobody has
used your link yet".

The information was never lost, only unjoined: every invitee still carries the
code they arrived on. So the edges are reconstructed from `users`, dated from
when the invitee registered rather than from now - the alternative is a
programme report that says everybody joined on deploy day.

Only the signup half. `converted_at`, `reward_paid` and `revenue_generated`
stay empty: those are paid at the first purchase, which has never fired either,
and inventing them here would credit rewards nobody was ever given.

Revision ID: 0028_backfill_referral_edges
Revises: 0027_one_claim_per_account
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_backfill_referral_edges"
down_revision = "0027_one_claim_per_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO referrals (
                id, referrer_id, invitee_id, code, joined_at,
                reward_paid, invitee_bonus_paid, revenue_generated,
                created_at, updated_at
            )
            SELECT
                'backfill-' || invitee.telegram_id::text,
                referrer.telegram_id,
                invitee.telegram_id,
                invitee.referred_by_code,
                invitee.created_at,
                0, 0, 0,
                now(), now()
            FROM users AS invitee
            JOIN users AS referrer
              ON referrer.referral_code = invitee.referred_by_code
            WHERE invitee.referred_by_code IS NOT NULL
              AND referrer.telegram_id <> invitee.telegram_id
              -- One edge per invitee, and never a second one for somebody the
              -- application has already recorded.
              AND NOT EXISTS (
                  SELECT 1 FROM referrals r WHERE r.invitee_id = invitee.telegram_id
              )
            -- The same Telegram account is a separate customer in every shop,
            -- so one person may appear as several `users` rows. The edge is
            -- between accounts, and its invitee column is unique.
            ON CONFLICT (invitee_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # Nothing to undo: these rows describe signups that really happened, and
    # deleting them would lose the same information a second time.
    pass
