"""Telegram Stars: paid inside Telegram, without leaving the chat.

The shop's own bot issues an invoice link in XTR, Telegram's currency for
digital goods, and the stars land in that bot's balance - our bot for our
customers, a reseller's bot for theirs. That is the only correct owner: a
reseller's customer paying stars into our bot would be paying us for a
package the reseller already bought.

**Verification asks Telegram, not the customer.** The bot's own transaction
list (`getStarTransactions`) carries the payload of every invoice paid, so
`verify` looks for this payment's id there. The `successful_payment` update
merely prompts that check sooner; the sweeper would find it anyway, which is
what keeps a payment from being lost when the bot was down at the moment it
was paid.

The operator sets the price of a star in Toman; that is stored where other
providers keep their merchant id, because a star account needs no
credential - the bot token is the credential, and the shop already has one.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final

import httpx

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    RefundDestination,
    VerificationOutcome,
)
from geekvpn.domain.payments.gateway import (
    CheckoutInstruction,
    GatewayCapabilities,
    RefundResult,
    VerificationResult,
)
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

API_URL: Final = "https://api.telegram.org"
TIMEOUT_SECONDS: Final = 15.0
#: Telegram pays out in seconds; the bot handler prompts sooner anyway.
RETRY_AFTER: Final = timedelta(seconds=30)
#: How far back the transaction list is read: pages of a hundred, newest
#: first. A payment older than this many transactions was long since settled
#: by the `successful_payment` handler or the sweeper.
PAGES: Final = 5
PAGE_SIZE: Final = 100

CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=True,
    supports_online_refund=False,
    supports_partial_refund=False,
    # The link opens Telegram's own payment sheet; nothing outside Telegram.
    requires_redirect=True,
    requires_manual_review=False,
)


class StarsError(RuntimeError):
    """Telegram refused or could not be reached."""


def stars_for(amount: Money, toman_per_star: int) -> int:
    """Rounded up: a fraction of a star rounded away is a discount nobody gave."""
    if toman_per_star <= 0:
        raise StarsError("The price of a star is not set.")
    return max(1, math.ceil(amount.amount / toman_per_star))


def _rate(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


@dataclass(slots=True)
class StarsGateway:
    merchant_id: str
    """The price of one star, in Toman, as the operator typed it."""

    bot_token: Callable[[], str] = lambda: ""
    api_url: str = API_URL
    key: str = "stars"
    title_fa: str = "⭐ پرداخت با استارز تلگرام"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = field(default_factory=lambda: CAPABILITIES)

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        stars = stars_for(amount, _rate(self.merchant_id))
        link = self._call(
            "createInvoiceLink",
            {
                "title": f"فاکتور {invoice_number}",
                "description": f"پرداخت {amount.amount:,} تومان",
                # What comes back in `successful_payment` and in the
                # transaction list - the one thing tying a star to a payment.
                "payload": payment_id,
                "currency": "XTR",
                "prices": [{"label": invoice_number, "amount": stars}],
            },
        )
        if not isinstance(link, str) or not link:
            raise StarsError("Telegram returned no invoice link.")
        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            amount=amount,
            redirect_url=link,
            instructions_fa=(
                f"⭐ <b>پرداخت با استارز</b>\n\n"
                f"مبلغ: <b>{stars:,}</b> استار (معادل {amount.amount:,} تومان)\n\n"
                "دکمهٔ زیر رو بزن و پرداخت رو تو خود تلگرام تأیید کن."
            ),
            metadata={"gatewayReference": f"{payment_id}:{stars}", "stars": str(stars)},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        payload, _, stars_text = reference.partition(":")
        try:
            wanted = int(stars_text)
        except ValueError:
            logger.warning("stars.bad_reference", payment_id=payment_id, reference=reference)
            return self._wait(reference)
        try:
            for offset in range(0, PAGES * PAGE_SIZE, PAGE_SIZE):
                result = self._call(
                    "getStarTransactions", {"offset": offset, "limit": PAGE_SIZE}
                )
                transactions = result.get("transactions") if isinstance(result, dict) else None
                if not transactions:
                    break
                found = _paid(transactions, payload=payload, wanted=wanted)
                if found is not None:
                    return VerificationResult(
                        outcome=VerificationOutcome.CONFIRMED,
                        amount=expected,
                        reference=reference,
                        raw={"transaction": found},
                    )
        except StarsError as failure:
            logger.warning("stars.verify_failed", payment_id=payment_id, error=str(failure))
        return self._wait(reference)

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa="بازگشت وجه پرداخت استارز به کیف پول انجام می‌شه.",
        )

    @staticmethod
    def _wait(reference: str) -> VerificationResult:
        # Never declined: an unpaid invoice link simply stays unpaid, and the
        # payment's own expiry closes it.
        return VerificationResult(
            outcome=VerificationOutcome.INCONCLUSIVE, reference=reference, retry_after=RETRY_AFTER
        )

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        token = self.bot_token()
        if not token:
            raise StarsError("This shop has no bot to take stars with.")
        try:
            response = httpx.post(
                f"{self.api_url}/bot{token}/{method}", json=payload, timeout=TIMEOUT_SECONDS
            )
            body = response.json()
        except (httpx.HTTPError, ValueError) as failure:
            raise StarsError(type(failure).__name__) from failure
        if not isinstance(body, dict) or not body.get("ok"):
            description = body.get("description") if isinstance(body, dict) else None
            raise StarsError(str(description or "Telegram refused the request."))
        return body.get("result")


def _paid(transactions: list[Any], *, payload: str, wanted: int) -> str | None:
    """The id of an incoming payment for this payload of at least `wanted`."""
    for transaction in transactions:
        if not isinstance(transaction, dict):
            continue
        source = transaction.get("source")
        if not isinstance(source, dict) or source.get("type") != "user":
            continue
        if source.get("invoice_payload") != payload:
            continue
        try:
            amount = int(transaction.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if amount >= wanted:
            return str(transaction.get("id") or "")
        logger.warning("stars.underpaid", payload=payload, got=amount, wanted=wanted)
    return None


__all__ = ["CAPABILITIES", "StarsError", "StarsGateway", "stars_for"]
