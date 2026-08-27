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


# -- orders, subscriptions, tickets, notifications --------------------------


def _source(path: str) -> ast.Module:
    return ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))


def _find(tree: ast.Module, class_name: str, method: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    and child.name == method
                ):
                    return child
    raise AssertionError(f"{class_name}.{method} is gone")


PROVISIONING = "src/geekvpn/infrastructure/persistence/repositories/provisioning.py"
SUPPORT = "src/geekvpn/infrastructure/persistence/repositories/sync_support.py"
NOTIFY = "src/geekvpn/infrastructure/persistence/repositories/sync_notifications.py"


@pytest.mark.parametrize(
    ("path", "class_name", "method"),
    [
        (PROVISIONING, "SqlAlchemyOrderRepository", "list_for_user"),
        (PROVISIONING, "SqlAlchemyOrderRepository", "count_for_user"),
        (PROVISIONING, "SqlAlchemySubscriptionRepository", "list_for_user"),
        (SUPPORT, "SyncTicketRepository", "for_user"),
        (SUPPORT, "SyncTicketRepository", "count_for_user"),
        (NOTIFY, "SyncNotificationRepository", "for_user"),
        (NOTIFY, "SyncNotificationRepository", "count_unread"),
        # Deduplication is per shop too: the same key in two shops is two
        # different notifications, and sharing it would silence one of them.
        (NOTIFY, "SyncNotificationRepository", "dedupe_exists"),
    ],
)
def test_every_remaining_per_customer_read_asks_which_shop(
    path: str, class_name: str, method: str
):
    """One person, two shops, two histories.

    A customer of ours who also buys from a reseller had one order list, one
    subscription list and one ticket thread between the two - the same shape
    as the wallet, in four more places.
    """
    assert _calls_shop(_find(_source(path), class_name, method))


@pytest.mark.parametrize(
    ("path", "class_name", "method"),
    [
        (PROVISIONING, "SqlAlchemyOrderRepository", "add"),
        (PROVISIONING, "SqlAlchemySubscriptionRepository", "add"),
        (SUPPORT, "SyncTicketRepository", "save"),
        (NOTIFY, "SyncNotificationRepository", "save"),
    ],
)
def test_every_remaining_insert_stamps_the_shop(path: str, class_name: str, method: str):
    assert _stamps_shop(_find(_source(path), class_name, method))


def test_a_first_purchase_is_per_shop():
    """"Have they bought before" is a question about *this* shop.

    A customer's first purchase from a reseller is a first purchase, whatever
    they have bought from us - and first-purchase pricing is money, so getting
    it from the wrong shop's history charges the wrong price.
    """
    assert _calls_shop(_find(_source(PROVISIONING), "SqlAlchemyOrderRepository", "has_completed_order"))


def test_both_scopes_hand_the_shop_over():
    """A repository that takes the argument and a scope that never passes it
    is a filter that is always `IS NULL` - and looks like working code."""
    asyncs = pathlib.Path("src/geekvpn/infrastructure/di/scope.py").read_text(encoding="utf-8")
    syncs = pathlib.Path("src/geekvpn/infrastructure/di/sync_scope.py").read_text(encoding="utf-8")

    for name in ("SqlAlchemyOrderRepository", "SqlAlchemySubscriptionRepository"):
        index = asyncs.index(f"{name}(")
        assert "reseller_id=" in asyncs[index : index + 200], name
    for name in ("SyncTicketRepository", "SyncNotificationRepository"):
        assert f"{name}(self.session, reseller_id=self.reseller_id)" in syncs, name
