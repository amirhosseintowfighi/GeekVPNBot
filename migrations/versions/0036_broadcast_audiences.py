"""Four more broadcast audiences.

Customers with no working service, buyers who have not bought lately, the
customers of one server, and customers with a suspended service. The column
is guarded by a check constraint listing every audience, so a new member of
`AudienceKind` needs this or every broadcast using it fails on insert.

Revision ID: 0036_broadcast_audiences
Revises: 0035_subscription_owner_settings
"""

from __future__ import annotations

from alembic import op

revision = "0036_broadcast_audiences"
down_revision = "0035_subscription_owner_settings"
branch_labels = None
depends_on = None

NAME = "ck_notify_broadcasts_notify_broadcasts_audience"

#: The constraint 0003 created was named through the naming convention and
#: then truncated to a hash (`..._notify_broadc_1f09`), so it is found by what
#: it checks rather than by a name that depends on the identifier limit.
DROP_AUDIENCE_CHECK = """
DO $$
DECLARE found text;
BEGIN
    FOR found IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'notify_broadcasts'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%audience_kind%'
    LOOP
        EXECUTE format('ALTER TABLE notify_broadcasts DROP CONSTRAINT %I', found);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(DROP_AUDIENCE_CHECK)
    op.create_check_constraint(
        op.f(NAME),
        "notify_broadcasts",
        "audience_kind IN ('all', 'active_subscribers', 'expired', 'expiring_soon', "
        "'never_purchased', 'tier', 'explicit', 'no_service', 'lapsed_buyers', "
        "'on_server', 'suspended_service')",
    )


def downgrade() -> None:
    # Rows using the new audiences would violate the narrower constraint. They
    # are records of broadcasts already sent; relabelled as `explicit` rather
    # than deleted, so the history of what was said survives.
    op.execute(
        "UPDATE notify_broadcasts SET audience_kind = 'explicit' "
        "WHERE audience_kind IN ('no_service', 'lapsed_buyers', 'on_server', 'suspended_service')"
    )
    op.execute(DROP_AUDIENCE_CHECK)
    op.create_check_constraint(
        op.f(NAME),
        "notify_broadcasts",
        "audience_kind IN ('all', 'active_subscribers', 'expired', 'expiring_soon', "
        "'never_purchased', 'tier', 'explicit')",
    )
