"""A Telegram account can be a customer of more than one shop.

`users.telegram_id` was globally unique, which was right while this platform
had one storefront. With resellers running their own bots it is wrong in a way
that loses people money: a person who buys from us and later opens a reseller's
bot gets handed *our* account for them - a wallet balance and a subscription
list belonging to a different seller, shown under a name they believe is the
reseller's.

The rule is now "one row per Telegram account per shop", and these hold both
halves of it: that the schema can express it, and that no lookup forgets to
ask which shop.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest

from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.persistence.models import UserModel

pytestmark = pytest.mark.unit

RESELLER = uuid.uuid4()


def test_a_customer_knows_which_shop_they_belong_to():
    person = User(
        uuid.uuid4(),
        telegram_id=87791922,
        referral_code="ABC123",
        reseller_id=str(RESELLER),
    )

    assert person.reseller_id == str(RESELLER)


def test_a_platform_customer_belongs_to_no_reseller():
    """`None` is a real answer - the platform's own bot - not "unknown"."""
    person = User(uuid.uuid4(), telegram_id=87791922, referral_code="ABC123")

    assert person.reseller_id is None


def test_the_schema_forbids_the_same_person_twice_in_one_shop():
    """Two partial indexes rather than one composite unique.

    Postgres treats NULLs as distinct, so `UNIQUE (telegram_id, reseller_id)`
    would happily accept the same person twice as a platform customer - which
    is the exact duplicate the old global constraint existed to prevent.
    """
    indexes = {index.name: index for index in UserModel.__table__.indexes}

    platform = indexes["uq_users_platform_telegram_id"]
    reseller = indexes["uq_users_reseller_telegram_id"]

    assert platform.unique and reseller.unique
    # Each is partial, and on opposite halves of the table.
    assert "IS NULL" in str(platform.dialect_options["postgresql"]["where"])
    assert "IS NOT NULL" in str(reseller.dialect_options["postgresql"]["where"])


def test_telegram_id_alone_is_no_longer_unique():
    """The old constraint has to be gone, or the new ones can never be
    satisfied by a reseller's customer who is also one of ours."""
    column = UserModel.__table__.columns["telegram_id"]

    assert not column.unique


def test_looking_a_customer_up_asks_which_shop():
    """The whole failure mode is one forgotten argument, in a query that
    otherwise works perfectly and returns the wrong person.

    Read from the source: a test that calls the repository needs a database,
    and this is checking a signature, not a result.
    """
    source = pathlib.Path(
        "src/geekvpn/infrastructure/persistence/repositories/user.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    lookup = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_by_telegram_id"
    )
    keyword_only = {arg.arg for arg in lookup.args.kwonlyargs}

    assert "reseller_id" in keyword_only
