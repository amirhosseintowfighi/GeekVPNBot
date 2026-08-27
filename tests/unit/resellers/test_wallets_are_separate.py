"""One Telegram account, two shops, two wallets.

The symptom was specific and alarming: starting a reseller's bot showed the
platform owner their own balance. Not a display bug - it was the same wallet
row, because the ledger is keyed by Telegram id and `0009` had only separated
the `users` table.

These read the SQL rather than exercising a database, because the thing that
went wrong is a missing `WHERE` clause and every one of these methods needs a
live Postgres to run. A query that filters on the shop is the whole fix; a
query that does not is the whole bug.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

SOURCE = pathlib.Path(
    "src/geekvpn/infrastructure/persistence/repositories/sync_payments.py"
).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _method(class_name: str, method: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method:
                    return child
    raise AssertionError(f"{class_name}.{method} is gone")


def _calls_shop(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_shop"
        for call in ast.walk(node)
    )


def _stamps_shop(node: ast.AST) -> bool:
    """Does this method write `reseller_id` onto a row before adding it?"""
    return any(
        isinstance(assign, ast.Assign)
        and any(
            isinstance(target, ast.Attribute) and target.attr == "reseller_id"
            for target in assign.targets
        )
        for assign in ast.walk(node)
    )


# -- the wallet, which is what leaked ---------------------------------------


def test_reading_a_wallet_asks_which_shop():
    assert _calls_shop(_method("SyncWalletRepository", "get_or_create"))


def test_writing_a_wallet_entry_stamps_the_shop():
    """The half that makes the other half safe.

    Filtering reads while leaving writes unstamped is worse than no scoping at
    all: a reseller's customer's credit lands in a row that customer cannot see
    and the platform can.
    """
    save = _method("SyncWalletRepository", "save")

    assert _stamps_shop(save)
    # And the "which entries do I already have" read is scoped too, or a
    # second shop's entry ids would count as known and be silently dropped.
    assert _calls_shop(save)


# -- invoices and payments ---------------------------------------------------


@pytest.mark.parametrize(
    ("class_name", "method"),
    [
        ("SyncInvoiceRepository", "list_for_user"),
        ("SyncInvoiceRepository", "count_for_user"),
        ("SyncPaymentRepository", "list_for_user"),
    ],
)
def test_every_per_customer_read_asks_which_shop(class_name: str, method: str):
    assert _calls_shop(_method(class_name, method))


@pytest.mark.parametrize(
    ("class_name", "method"),
    [("SyncInvoiceRepository", "save"), ("SyncPaymentRepository", "save")],
)
def test_every_insert_stamps_the_shop(class_name: str, method: str):
    assert _stamps_shop(_method(class_name, method))


def test_the_operator_queue_is_deliberately_not_scoped():
    """The one exception, and it has to stay one.

    The platform operator reviews every receipt, a reseller's customers'
    included - that is what was asked for, and scoping it would hand the queue
    to a reseller who has no screen to review it on, where the receipt would
    reach nobody.

    Pinned so that "scope everything" applied later does not quietly orphan
    them. When resellers get that screen this needs an argument, not the
    scope's own shop.
    """
    queue = _method("SyncPaymentRepository", "in_state")

    assert not _calls_shop(queue)
    assert "Every shop, on purpose" in ast.get_docstring(queue or "")


def test_the_scope_hands_the_shop_to_all_three():
    """A repository that takes the argument and a scope that never passes it
    is a filter that is always `IS NULL` - which looks exactly like working
    code from every side."""
    wiring = pathlib.Path(
        "src/geekvpn/infrastructure/di/sync_scope.py"
    ).read_text(encoding="utf-8")

    for name in (
        "SyncWalletRepository",
        "SyncInvoiceRepository",
        "SyncPaymentRepository",
    ):
        assert f"{name}(self.session, reseller_id=self.reseller_id)" in wiring, name
