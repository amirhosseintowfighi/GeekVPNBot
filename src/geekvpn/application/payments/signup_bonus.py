"""Credit a new customer's wallet the first time they arrive.

A shop-front decision, not a payment one: nobody paid, and no invoice exists.
It lives beside the wallet because that is the aggregate it touches, and
because `credit_reward` - written for exactly this shape of "earned by a rule
rather than decided by a person" credit - had no caller at all until now.

Two rules carry the weight.

**It cannot pay twice.** The reference is derived from the customer, so a
second attempt writes the same `(user_id, kind, reference)` the ledger already
holds a unique constraint on. Belt and braces: the check below usually catches
it first, and the constraint catches the race the check cannot.

**It is the platform's offer, not a reseller's.** The amount comes from our
settings, and a reseller's customer buys with the reseller's money - so
crediting one on our say-so would spend somebody else's margin on a promotion
they never agreed to. A reseller wanting this needs their own setting, which
does not exist yet.
"""

from __future__ import annotations

from geekvpn.application.payments.ports import WalletRepository
from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.wallet import LedgerEntry

#: What the ledger entry is keyed on. One per customer, forever.
REFERENCE = "signup-bonus"

#: Recorded as cashback rather than an adjustment: an adjustment means a person
#: decided, and always carries an actor and a reason. Nobody decided this one -
#: a rule fired.
KIND = TransactionKind.CASHBACK


class SignupBonusService:
    """Grants the welcome credit, or declines to, for one shop."""

    def __init__(
        self,
        *,
        wallets: WalletService,
        ledger: WalletRepository,
        reseller_id: object | None = None,
    ) -> None:
        self._wallets = wallets
        #: Read directly, because asking "has this customer had one" is a
        #: question about the ledger, not an operation on it.
        self._ledger = ledger
        self._reseller_id = reseller_id

    def grant(self, *, user_id: int, amount_toman: int, note_fa: str) -> LedgerEntry | None:
        """Credit the bonus. Returns `None` when nothing was given.

        `None` is an ordinary answer, not a failure: it is what a switched-off
        bonus, a reseller's shop, and a customer who already has one all look
        like, and the caller treats all three the same way.
        """
        if amount_toman <= 0:
            return None
        if self._reseller_id is not None:
            return None
        if self._already_granted(user_id):
            return None

        return self._wallets.credit_reward(
            user_id=user_id,
            amount=Money(amount_toman),
            kind=KIND,
            description_fa=note_fa,
            reference=REFERENCE,
        )

    def _already_granted(self, user_id: int) -> bool:
        wallet = self._ledger.get_or_create(user_id)
        return any(
            entry.kind is KIND and entry.reference == REFERENCE for entry in wallet.entries
        )


__all__ = ["KIND", "REFERENCE", "SignupBonusService"]
