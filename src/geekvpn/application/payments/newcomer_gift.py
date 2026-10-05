"""Credit for a newcomer who joined and has not bought yet.

Somebody who started the bot a day ago and bought nothing is the cheapest
customer there is to win: they already chose this shop once. The operator
picks the wait and the amount; the worker runs this every hour.

Once per person, ever: the ledger's unique ``(user, kind, reference)`` is the
guarantee, and the candidate query leaves out whoever already has the entry.
Who counts as "has not bought" is the query's business too - this service
only decides when to look and what to give.

The platform's shop only, for the reason the signup bonus gives: a
reseller's customer spends the reseller's margin, and a promotion they never
agreed to is not ours to run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.application.ports.clock import Clock
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind

_log = logging.getLogger(__name__)

REFERENCE = "newcomer-gift"
#: How far back past the wait to look. Without a floor, switching the gift on
#: would pay every member the shop has ever had who never bought.
LOOKBACK = timedelta(days=7)
DESCRIPTION_FA = "هدیهٔ خوش‌آمد"


class NewcomerGift:
    def __init__(
        self,
        *,
        wallets: WalletService,
        #: Customers who joined in ``[after, before)``, have bought nothing
        #: and have not had this gift.
        candidates: Callable[[datetime, datetime], Sequence[int]],
        #: Tells one customer, with the operator's words. May fail: the credit
        #: stands either way.
        notify: Callable[[int, int, str], None],
        clock: Clock,
    ) -> None:
        self._wallets = wallets
        self._candidates = candidates
        self._notify = notify
        self._clock = clock

    def run(self, *, after_hours: int, amount_toman: int, message_fa: str) -> list[int]:
        """Credit everyone due. Returns their Telegram ids."""
        if after_hours <= 0 or amount_toman <= 0:
            return []
        before = self._clock.now() - timedelta(hours=after_hours)
        given: list[int] = []
        for user_id in self._candidates(before - LOOKBACK, before):
            self._wallets.credit_reward(
                user_id=user_id,
                amount=Money(amount_toman),
                # Cashback, as the signup bonus is: a rule fired, nobody decided.
                kind=TransactionKind.CASHBACK,
                description_fa=DESCRIPTION_FA,
                reference=REFERENCE,
            )
            given.append(user_id)
            if message_fa.strip():
                try:
                    self._notify(user_id, amount_toman, message_fa)
                except Exception:
                    _log.warning("newcomer_gift.not_told user=%s", user_id, exc_info=True)
        return given


__all__ = ["DESCRIPTION_FA", "LOOKBACK", "REFERENCE", "NewcomerGift"]
