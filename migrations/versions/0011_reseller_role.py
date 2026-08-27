"""The database did not know about the reseller role.

`admins.role` carries a check constraint listing the roles that existed when
the table was created. Adding a member to `AdminRole` updated the *model's*
constraint - which nothing applies to a live database - and left the deployed
one unchanged, so every attempt to create a reseller failed on an insert the
API could only report as "something went wrong".

That is the shape of the bug rather than its detail: an enum in Python and a
list of strings frozen in a migration, with nothing holding them together.
`tests/integration/test_enum_constraints_match.py` holds them together now.

Revision ID: 0011_reseller_role
Revises: 0010_reseller_cards
"""

from __future__ import annotations

from alembic import op

revision = "0011_reseller_role"
down_revision = "0010_reseller_cards"
branch_labels = None
depends_on = None

# Written out rather than built from a variable or from the enum. A migration
# is a record of what was applied on a particular day, and one that reads the
# current enum would silently change meaning the next time somebody edits it.
# It also has to be literal for `test_enum_constraints_match` to read it, which
# is the check that would have caught this bug in the first place.


def upgrade() -> None:
    op.drop_constraint("ck_admins_role", "admins", type_="check")
    op.create_check_constraint(
        "ck_admins_role",
        "admins",
        "role IN ('super_admin', 'admin', 'finance', 'support', 'viewer', 'reseller')",
    )


def downgrade() -> None:
    # Reseller logins would violate the narrower constraint, and they are the
    # only way a reseller signs in. Removing the accounts is the only way back,
    # and it takes their reseller records with them by cascade.
    op.execute("DELETE FROM admins WHERE role = 'reseller'")
    op.drop_constraint("ck_admins_role", "admins", type_="check")
    op.create_check_constraint(
        "ck_admins_role",
        "admins",
        "role IN ('super_admin', 'admin', 'finance', 'support', 'viewer')",
    )
