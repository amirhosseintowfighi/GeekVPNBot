"""Identity, sessions, audit log and runtime settings.

Revision ID: 0001_identity_and_audit
Revises:
Create Date: Phase 2

The audit table is made append-only with two rules rather than a trigger:
rules are applied during query rewriting, so an UPDATE or DELETE becomes
literally nothing - there is no application code path, including one running
with a compromised database account, that can rewrite history. Only the table
owner (used by migrations) can drop them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_identity_and_audit"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_premium", sa.Boolean(), nullable=False),
        sa.Column("photo_url", sa.String(length=512), nullable=True),
        sa.Column("referral_code", sa.String(length=16), nullable=False),
        sa.Column("referred_by_code", sa.String(length=16), nullable=True),
        sa.Column("suspended_reason", sa.String(length=256), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'suspended', 'deleted')", name="ck_users_status"),
        sa.CheckConstraint("language IN ('fa', 'en')", name="ck_users_language"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        sa.UniqueConstraint("referral_code", name="uq_users_referral_code"),
    )
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index("ix_users_created_at", "users", ["created_at"])
    op.create_index("ix_users_referred_by_code_status", "users", ["referred_by_code", "status"])

    op.create_table(
        "admins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=True),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("granted_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("denied_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
        sa.Column("is_totp_enabled", sa.Boolean(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('super_admin', 'admin', 'finance', 'support', 'viewer')",
            name="ck_admins_role",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_admins_status"),
        sa.CheckConstraint("failed_attempts >= 0", name="ck_admins_failed_attempts"),
        sa.PrimaryKeyConstraint("id", name="pk_admins"),
        sa.UniqueConstraint("username", name="uq_admins_username"),
        sa.UniqueConstraint("email", name="uq_admins_email"),
        sa.UniqueConstraint("telegram_id", name="uq_admins_telegram_id"),
    )
    op.create_index("ix_admins_role", "admins", ["role"])

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_method", sa.String(length=32), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("device_label", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "subject_type IN ('user', 'admin', 'system')", name="ck_sessions_subject_type"
        ),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN "
            "('logout', 'logout_all', 'token_reuse', 'admin_revoked', "
            "'password_changed', 'account_suspended', 'expired')",
            name="ck_sessions_revocation_reason",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
    )
    op.create_index("ix_sessions_subject_id_revoked_at", "sessions", ["subject_id", "revoked_at"])
    op.create_index("ix_sessions_absolute_expires_at", "sessions", ["absolute_expires_at"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_refresh_tokens_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(length=128), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("outcome IN ('success', 'failure')", name="ck_audit_outcome"),
        sa.CheckConstraint("actor_type IN ('user', 'admin', 'system')", name="ck_audit_actor_type"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])
    op.create_index("ix_audit_logs_actor_id_occurred_at", "audit_logs", ["actor_id", "occurred_at"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])

    # Append-only. Nothing the application can do rewrites the audit trail.
    op.execute("CREATE RULE audit_logs_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING")
    op.execute("CREATE RULE audit_logs_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING")

    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name="pk_platform_settings"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.execute("DROP RULE IF EXISTS audit_logs_no_delete ON audit_logs")
    op.execute("DROP RULE IF EXISTS audit_logs_no_update ON audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("sessions")
    op.drop_table("admins")
    op.drop_table("users")
