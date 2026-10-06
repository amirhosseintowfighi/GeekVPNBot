"""A customer sending wallet balance to another customer of the same shop.

The shop decides whether it is allowed at all and the smallest amount worth
moving. Only to somebody who has started this shop's bot: balance sent to a
Telegram id nobody here owns would sit in a wallet nobody can open, and one
sent across shops would move money between two businesses' books.

The operator is told about every transfer. Moving balance between accounts is
how a stolen account is emptied, and the reports chat is where somebody
notices.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.errors import WalletTransferRefused
from geekvpn.domain.payments.wallet import LedgerEntry

_log = logging.getLogger(__name__)


class WalletTransfers:
    def __init__(
        self,
        *,
        wallets: WalletService,
        #: Whether this Telegram id is a customer of this shop.
        is_customer: Callable[[int], bool],
        enabled: Callable[[], bool],
        minimum_toman: Callable[[], int],
        #: Sender, recipient, amount - for the operators. Never fails a transfer.
        report: Callable[[int, int, int], None] | None,
    ) -> None:
        self._wallets = wallets
        self._is_customer = is_customer
        self._enabled = enabled
        self._minimum = minimum_toman
        self._report = report

    def transfer(self, *, from_user: int, to_user: int, amount_toman: int) -> LedgerEntry:
        """
        :raises WalletTransferRefused: with the reason in Persian.
        :raises InsufficientFunds: the sender's balance does not cover it.
        """
        if not self._enabled():
            raise WalletTransferRefused("انتقال موجودی در این فروشگاه فعال نیست.")
        minimum = self._minimum()
        if amount_toman < max(minimum, 1):
            raise WalletTransferRefused(f"حداقل مبلغ انتقال {minimum:,} تومانه.")
        if to_user == from_user:
            raise WalletTransferRefused("نمی‌تونی به خودت انتقال بدی.")
        if not self._is_customer(to_user):
            raise WalletTransferRefused(
                "کاربری با این آیدی عددی پیدا نشد. باید یک بار ربات رو استارت کرده باشه."
            )
        entry = self._wallets.transfer(
            from_user=from_user,
            to_user=to_user,
            amount=Money(amount_toman),
            reference=f"transfer:{uuid.uuid4().hex[:16]}",
        )
        if self._report is not None:
            try:
                self._report(from_user, to_user, amount_toman)
            except Exception:
                # The money has moved; a lost report is not worth undoing it.
                _log.warning("wallet_transfer.report_failed", exc_info=True)
        return entry


__all__ = ["WalletTransfers"]
