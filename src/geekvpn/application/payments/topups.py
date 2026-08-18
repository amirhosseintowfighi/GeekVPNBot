"""Crediting a settled top-up.

``begin_topup`` has always tagged the invoice ``{"kind": "topup"}`` and nothing
ever read it. ``Wallet.top_up`` had no callers either, so a customer could send
money, watch an operator approve it, and see their balance stay where it was.

Two approval paths exist - a reviewer approving a receipt, and the verification
service settling a gateway callback - and both must credit identically. Hence
one function rather than the same block written twice: a top-up that credits on
one path and not the other is worse than one that credits on neither, because
it looks like it works.
"""

from __future__ import annotations

from datetime import datetime

from geekvpn.application.payments.ports import WalletRepository
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.invoice import Invoice
from geekvpn.domain.payments.wallet import Wallet

#: What ``CheckoutService.begin_topup`` stamps on the invoice it issues.
TOPUP_METADATA_KEY = "kind"
TOPUP_METADATA_VALUE = "topup"


def is_topup(invoice: Invoice) -> bool:
    return invoice.metadata.get(TOPUP_METADATA_KEY) == TOPUP_METADATA_VALUE


def credit_topup(
    invoice: Invoice,
    *,
    wallets: WalletRepository,
    amount: Money,
    entry_id: str,
    now: datetime,
) -> Wallet | None:
    """Credit the principal of a settled top-up. ``None`` when not a top-up.

    The reference is the invoice number, which makes this idempotent through
    ``uq_wallet_user_kind_reference``: a second approval of the same invoice
    cannot credit twice, and that guarantee lives in the database rather than
    in whichever caller happens to run second.

    Only the principal. Any surplus is credited separately as an overpayment by
    the caller, because the two are different kinds of money and a customer
    reading their statement is entitled to see which is which.
    """
    if not is_topup(invoice):
        return None

    # The lock is what makes the read-modify-write safe against a second
    # operator approving a different payment for the same customer.
    wallets.lock(invoice.user_id)
    wallet = wallets.get_or_create(invoice.user_id)
    wallet.top_up(amount, entry_id=entry_id, occurred_at=now, reference=invoice.number)
    wallets.save(wallet)
    return wallet


__all__ = ["TOPUP_METADATA_KEY", "TOPUP_METADATA_VALUE", "credit_topup", "is_topup"]
