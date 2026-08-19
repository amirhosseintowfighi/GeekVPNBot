"""Security and performance indexes.

Revision ID: 0004_security_indexes
Revises: 0003_billing_and_support
Create Date: Phase 13

No new tables. Every index here answers a query that already exists in the
codebase and currently causes a sequential scan, plus three columns that the
encryption work needs.

How each index was chosen
-------------------------
Not by guessing. Each one names the repository method it serves:

* ``ix_billing_payments_review_queue`` - ``SyncPaymentRepository.in_state``
  filters on ``state`` and orders by ``submitted_at`` ascending. Without a
  composite index Postgres scans every payment ever made and sorts the result to
  render the operator's review queue, which is the single most frequently opened
  admin screen.
* ``ix_support_tickets_queue`` - ``SyncTicketRepository.queue`` filters on the
  three open states and orders by ``waiting_since`` with nulls last. Partial, so
  the index holds only open tickets; closed tickets accumulate forever and are
  never in this query.
* ``ix_notify_notifications_due`` - the deferred flush looks for pending rows
  whose ``send_after`` has passed. Partial again: sent notifications are the vast
  majority of the table and are never scanned by this job.
* ``ix_billing_wallet_entries_user_time`` - every wallet statement is "this
  user's entries, newest first, one page". The existing single-column index on
  ``user_id`` still requires a sort of a heavy customer's whole ledger.
* ``ix_support_messages_body_trgm`` - ``SyncTicketRepository.search`` uses
  ``ILIKE '%term%'``. A leading wildcard cannot use a B-tree at all, so this was
  guaranteed to be a full scan of every support message. Trigram is the fix, and
  the extension is created here rather than assumed.
* ``ix_billing_payments_gateway_lookup`` - the crypto/gateway callback path looks
  a payment up by ``(gateway_key, gateway_reference)``. Unique, because two
  payments sharing one gateway reference is a double-credit waiting to happen,
  and the database is the only place that check cannot be raced.

The new columns
---------------
``billing_payments.proof_encrypted`` and ``billing_card_accounts.card_encrypted``
hold AES-256-GCM tokens from ``infrastructure/security/crypto.py``.
``billing_card_accounts.card_blind_index`` holds the HMAC blind index, which is
what makes an encrypted card number searchable at all - a GCM ciphertext is
different every time it is written, so an equality lookup on it is impossible.

All three are nullable and no data is migrated. Encrypting existing rows requires
the master key at migration time, and a migration that fails halfway through
re-encrypting payment data is not a situation worth designing for; a separate
backfill command that can be re-run is. The columns are added here so the
backfill has somewhere to write.

Why ``postgresql_concurrently`` is **not** used
-----------------------------------------------
Concurrent index builds cannot run inside a transaction, and ``env.py`` takes an
advisory lock and runs the whole migration in one. Adding them concurrently would
mean either dropping that lock - allowing two deployments to migrate at once - or
autocommit blocks that leave invalid indexes behind on failure. At current table
sizes a plain build takes seconds. If these tables reach tens of millions of
rows, the right answer is a separate maintenance script, not a weaker lock.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_security_indexes"
down_revision = "0003_billing_and_support"
branch_labels = None
depends_on = None

OPEN_TICKET_STATES = "('open', 'waiting_user', 'answered')"
REVIEWABLE_PAYMENT_STATES = "('pending_review', 'awaiting_proof', 'pending_gateway')"


def upgrade() -> None:
    # --- columns for encryption at rest ------------------------------------
    op.add_column(
        "billing_payments",
        sa.Column("proof_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "billing_card_accounts",
        sa.Column("card_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "billing_card_accounts",
        sa.Column("card_blind_index", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_billing_card_accounts_card_blind_index",
        "billing_card_accounts",
        ["card_blind_index"],
    )

    # --- the operator review queue ----------------------------------------
    op.create_index(
        "ix_billing_payments_review_queue",
        "billing_payments",
        ["state", "submitted_at"],
        postgresql_where=sa.text(f"state IN {REVIEWABLE_PAYMENT_STATES}"),
    )
    op.create_index(
        "ix_billing_payments_gateway_lookup",
        "billing_payments",
        ["gateway_key", "gateway_reference"],
        unique=True,
        postgresql_where=sa.text("gateway_reference IS NOT NULL"),
    )
    op.create_index(
        "ix_billing_payments_expiry_sweep",
        "billing_payments",
        ["expires_at"],
        postgresql_where=sa.text(f"state IN {REVIEWABLE_PAYMENT_STATES}"),
    )

    # ix_billing_payments_user_state, ix_billing_invoices_user_state and
    # ix_subscriptions_user_state are deliberately absent: 0003 already
    # creates all three, and recreating them raises DuplicateTable on every
    # fresh upgrade. They are dropped by 0003's downgrade, not this one.

    # --- wallet statements --------------------------------------------------
    op.create_index(
        "ix_billing_wallet_entries_user_time",
        "billing_wallet_entries",
        ["user_id", sa.text("occurred_at DESC")],
    )

    # --- invoices ----------------------------------------------------------

    # --- the support queue --------------------------------------------------
    op.create_index(
        "ix_support_tickets_queue",
        "support_tickets",
        ["state", "priority", "waiting_since"],
        postgresql_where=sa.text(f"state IN {OPEN_TICKET_STATES}"),
    )
    op.create_index(
        "ix_support_tickets_assignee_open",
        "support_tickets",
        ["assignee_id"],
        postgresql_where=sa.text(f"state IN {OPEN_TICKET_STATES}"),
    )
    op.create_index(
        "ix_support_messages_ticket_time",
        "support_messages",
        ["ticket_id", "sent_at"],
    )

    # --- ticket search -----------------------------------------------------
    # ILIKE '%term%' cannot use a B-tree index in any form. Without trigram
    # support the search endpoint reads every message in the database.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_support_messages_body_trgm",
        "support_messages",
        ["body_fa"],
        postgresql_using="gin",
        postgresql_ops={"body_fa": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_support_tickets_subject_trgm",
        "support_tickets",
        ["subject_fa"],
        postgresql_using="gin",
        postgresql_ops={"subject_fa": "gin_trgm_ops"},
    )

    # --- notification delivery ---------------------------------------------
    op.create_index(
        "ix_notify_notifications_due",
        "notify_notifications",
        ["send_after"],
        postgresql_where=sa.text("state IN ('pending', 'deferred')"),
    )
    op.create_index(
        "ix_notify_notifications_user_unread",
        "notify_notifications",
        ["user_id", "queued_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index(
        "ix_notify_notifications_broadcast",
        "notify_notifications",
        ["broadcast_id"],
        postgresql_where=sa.text("broadcast_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notify_broadcasts_due",
        "notify_broadcasts",
        ["scheduled_for"],
        postgresql_where=sa.text("state IN ('scheduled', 'sending')"),
    )

    # --- provisioning ------------------------------------------------------
    op.create_index(
        "ix_subscriptions_expiry_sweep",
        "subscriptions",
        ["expires_at"],
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "ix_orders_user_time",
        "orders",
        ["user_id", sa.text("placed_at DESC")],
    )

    # --- security investigation -------------------------------------------
    # An audit log you cannot query during an incident is a log you do not have.
    op.create_index(
        "ix_audit_logs_actor_time",
        "audit_logs",
        ["actor_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_action_time",
        "audit_logs",
        ["action", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_failures",
        "audit_logs",
        [sa.text("occurred_at DESC")],
        postgresql_where=sa.text("outcome = 'failure'"),
    )


def downgrade() -> None:
    for name, table in (
        ("ix_audit_logs_failures", "audit_logs"),
        ("ix_audit_logs_action_time", "audit_logs"),
        ("ix_audit_logs_actor_time", "audit_logs"),
        ("ix_orders_user_time", "orders"),
        ("ix_subscriptions_expiry_sweep", "subscriptions"),
        ("ix_notify_broadcasts_due", "notify_broadcasts"),
        ("ix_notify_notifications_broadcast", "notify_notifications"),
        ("ix_notify_notifications_user_unread", "notify_notifications"),
        ("ix_notify_notifications_due", "notify_notifications"),
        ("ix_support_tickets_subject_trgm", "support_tickets"),
        ("ix_support_messages_body_trgm", "support_messages"),
        ("ix_support_messages_ticket_time", "support_messages"),
        ("ix_support_tickets_assignee_open", "support_tickets"),
        ("ix_support_tickets_queue", "support_tickets"),
        ("ix_billing_wallet_entries_user_time", "billing_wallet_entries"),
        ("ix_billing_payments_expiry_sweep", "billing_payments"),
        ("ix_billing_payments_gateway_lookup", "billing_payments"),
        ("ix_billing_payments_review_queue", "billing_payments"),
        ("ix_billing_card_accounts_card_blind_index", "billing_card_accounts"),
    ):
        op.drop_index(name, table_name=table)

    op.drop_column("billing_card_accounts", "card_blind_index")
    op.drop_column("billing_card_accounts", "card_encrypted")
    op.drop_column("billing_payments", "proof_encrypted")
    # pg_trgm is deliberately left installed. Dropping an extension another
    # object might depend on is a worse outcome than leaving it in place.
