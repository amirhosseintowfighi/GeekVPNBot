"""NowPayments, Plisio and TON: crypto that confirms itself.

The manual crypto method shows an address and waits for a person to check the
chain. These three check it for us, so the payment settles the moment the
coins arrive and nobody is woken up for it.

**The rate is the operator's.** This platform prices in Toman and none of
these speak it, so each converts at a rate the operator sets in the panel
(Toman per dollar, Toman per TON). A rate fetched from some exchange would be
somebody else's opinion of the price at a moment nobody chose; a rate the
operator typed is the price they decided to charge. A rate of zero means "not
set", and `begin` refuses rather than charging nothing.

**Unreachable is never declined.** Every one of these is asked again by the
sweeper, so a timeout answers INCONCLUSIVE. A wrong "declined" costs a
customer their money; asking again costs one request.

**What verify needs travels in the reference.** `verify` is given the
reference and the expected Toman and nothing else - so the figure in coins
the customer was asked for is packed into the reference when the payment
starts. Re-deriving it at verify time from today's rate would fail a payment
made at yesterday's.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_UP, Decimal
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

TIMEOUT_SECONDS: Final = 15.0

#: Blocks take minutes, not seconds; asking every few seconds buys nothing.
RETRY_AFTER: Final = timedelta(minutes=1)

NOWPAYMENTS_URL: Final = "https://api.nowpayments.io/v1"
PLISIO_URL: Final = "https://api.plisio.net/api/v1"
TONCENTER_URL: Final = "https://toncenter.com/api/v2"

NANO_PER_TON: Final = 1_000_000_000

#: The customer pays in their wallet app, and the chain decides when it is
#: done. No redirect for the address-based two; Plisio sends them to its page.
ADDRESS_CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=True,
    supports_online_refund=False,
    supports_partial_refund=False,
    requires_redirect=False,
    requires_manual_review=False,
)
REDIRECT_CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=True,
    supports_online_refund=False,
    supports_partial_refund=False,
    requires_redirect=True,
    requires_manual_review=False,
)

_NO_ONLINE_REFUND = RefundResult(
    succeeded=False,
    destination=RefundDestination.WALLET,
    message_fa="بازگشت وجه پرداخت ارزی به کیف پول انجام می‌شه.",
)


class CryptoGatewayError(RuntimeError):
    """Refused, unreachable or unreadable - the caller does the same thing."""


@dataclass(frozen=True, slots=True)
class ExchangeRates:
    """The operator's prices, read when the registry is built."""

    usd_toman: int = 0
    ton_toman: int = 0
    nowpayments_currency: str = "usdttrc20"
    #: Empty lets the customer choose on Plisio's page.
    plisio_currency: str = ""


def _no_rates() -> ExchangeRates:
    return ExchangeRates()


def toman_to_usd(amount: Money, rate: int) -> Decimal:
    """Dollars, rounded *up* to the cent: a rounding down is a discount
    nobody decided to give, on every payment."""
    if rate <= 0:
        raise CryptoGatewayError("The dollar rate is not set.")
    return (Decimal(amount.amount) / Decimal(rate)).quantize(Decimal("0.01"), rounding=ROUND_UP)


def toman_to_nanoton(amount: Money, rate: int) -> int:
    if rate <= 0:
        raise CryptoGatewayError("The TON rate is not set.")
    return math.ceil(amount.amount * NANO_PER_TON / rate)


def _inconclusive(reference: str, **raw: Any) -> VerificationResult:
    return VerificationResult(
        outcome=VerificationOutcome.INCONCLUSIVE,
        reference=reference,
        raw=dict(raw),
        retry_after=RETRY_AFTER,
    )


def _request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = httpx.request(
            method, url, params=params, json=json, headers=headers, timeout=TIMEOUT_SECONDS
        )
    except httpx.HTTPError as failure:
        raise CryptoGatewayError(str(failure)) from failure
    try:
        body = response.json()
    except ValueError as failure:
        raise CryptoGatewayError(response.text[:200]) from failure
    if not isinstance(body, dict):
        raise CryptoGatewayError("The provider did not answer with an object.")
    if response.status_code >= 400:
        raise CryptoGatewayError(str(body.get("message") or response.status_code))
    return body


# -- NowPayments ---------------------------------------------------------------


@dataclass(slots=True)
class NowPaymentsGateway:
    """A payment in one coin, to an address shown in our own chat.

    A payment rather than an invoice: an invoice's status can only be read
    with the merchant's email and password, a payment's with the API key we
    already hold - and the customer never leaves the bot.
    """

    merchant_id: str
    """The API key."""

    rates: Callable[[], ExchangeRates] = _no_rates
    base_url: str = NOWPAYMENTS_URL
    key: str = "nowpayments"
    title_fa: str = "پرداخت ارزی (NowPayments)"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = field(default_factory=lambda: ADDRESS_CAPABILITIES)

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        rates = self.rates()
        usd = toman_to_usd(amount, rates.usd_toman)
        body = _request(
            "POST",
            f"{self.base_url}/payment",
            json={
                "price_amount": float(usd),
                "price_currency": "usd",
                "pay_currency": rates.nowpayments_currency,
                "order_id": payment_id,
                "order_description": invoice_number,
            },
            headers={"x-api-key": self.merchant_id},
        )
        reference = body.get("payment_id")
        address = str(body.get("pay_address") or "")
        if reference is None or not address:
            raise CryptoGatewayError("The payment response carried no id or address.")
        pay_amount = str(body.get("pay_amount") or "")
        currency = str(body.get("pay_currency") or rates.nowpayments_currency).upper()
        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            amount=amount,
            address=address,
            network=currency,
            instructions_fa=_address_text(
                coin=currency, amount=pay_amount, address=address, toman=amount
            ),
            metadata={"gatewayReference": str(reference), "cryptoAmount": pay_amount},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        try:
            body = _request(
                "GET",
                f"{self.base_url}/payment/{reference}",
                headers={"x-api-key": self.merchant_id},
            )
        except CryptoGatewayError as failure:
            logger.warning("nowpayments.verify_failed", payment_id=payment_id, error=str(failure))
            return _inconclusive(reference)
        status = str(body.get("payment_status") or "").lower()
        if status in {"finished", "confirmed"}:
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED,
                amount=expected,
                reference=reference,
                raw={"status": status},
            )
        if status in {"failed", "expired", "refunded"}:
            return VerificationResult(
                outcome=VerificationOutcome.DECLINED,
                reference=reference,
                raw={"status": status},
                message_fa="پرداخت ارزی انجام نشد یا مهلتش تموم شد.",
            )
        # waiting, confirming, sending, partially_paid: still on its way, or
        # short - a short payment is for an operator to resolve, not a refusal.
        return _inconclusive(reference, status=status)

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return _NO_ONLINE_REFUND


# -- Plisio ------------------------------------------------------------------


@dataclass(slots=True)
class PlisioGateway:
    """An invoice on Plisio's page, where the customer chooses the coin."""

    merchant_id: str
    """The secret key."""

    rates: Callable[[], ExchangeRates] = _no_rates
    base_url: str = PLISIO_URL
    key: str = "plisio"
    title_fa: str = "پرداخت ارزی (Plisio)"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = field(default_factory=lambda: REDIRECT_CAPABILITIES)

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        rates = self.rates()
        params: dict[str, Any] = {
            "source_currency": "USD",
            "source_amount": str(toman_to_usd(amount, rates.usd_toman)),
            "order_number": payment_id,
            "order_name": invoice_number,
            "api_key": self.merchant_id,
        }
        if rates.plisio_currency:
            params["currency"] = rates.plisio_currency
        if callback_url:
            params["success_callback_url"] = callback_url
            params["fail_callback_url"] = callback_url
        body = _plisio(f"{self.base_url}/invoices/new", params)
        reference = body.get("txn_id")
        url = str(body.get("invoice_url") or "")
        if not reference or not url:
            raise CryptoGatewayError("The invoice response carried no id or link.")
        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            amount=amount,
            redirect_url=url,
            metadata={"gatewayReference": str(reference)},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        try:
            body = _plisio(f"{self.base_url}/operations/{reference}", {"api_key": self.merchant_id})
        except CryptoGatewayError as failure:
            logger.warning("plisio.verify_failed", payment_id=payment_id, error=str(failure))
            return _inconclusive(reference)
        status = str(body.get("status") or "").lower()
        # "mismatch" is an overpayment: the customer paid more, never less.
        if status in {"completed", "mismatch"}:
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED,
                amount=expected,
                reference=reference,
                raw={"status": status},
            )
        if status in {"expired", "cancelled", "cancelled duplicate", "error"}:
            return VerificationResult(
                outcome=VerificationOutcome.DECLINED,
                reference=reference,
                raw={"status": status},
                message_fa="پرداخت ارزی انجام نشد یا مهلتش تموم شد.",
            )
        return _inconclusive(reference, status=status)

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return _NO_ONLINE_REFUND


def _plisio(url: str, params: dict[str, Any]) -> dict[str, Any]:
    body = _request("GET", url, params=params)
    data = body.get("data")
    if body.get("status") != "success" or not isinstance(data, dict):
        message = data.get("message") if isinstance(data, dict) else None
        raise CryptoGatewayError(str(message or "Plisio refused the request."))
    return data


# -- TON ---------------------------------------------------------------------


@dataclass(slots=True)
class TonGateway:
    """Straight to the shop's own TON wallet, matched by a comment.

    Every payment gets its own comment, and the chain is read through
    toncenter for an incoming transfer that carries it and at least the
    amount asked. The coins never pass through anybody else.

    The credential is the wallet address, optionally followed by ``|`` and a
    toncenter API key: without one toncenter allows a request a second, which
    is plenty for a shop and not for a busy one.
    """

    merchant_id: str
    rates: Callable[[], ExchangeRates] = _no_rates
    base_url: str = TONCENTER_URL
    key: str = "ton"
    title_fa: str = "پرداخت با TON"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = field(default_factory=lambda: ADDRESS_CAPABILITIES)

    @property
    def address(self) -> str:
        return self.merchant_id.split("|", 1)[0].strip()

    @property
    def api_key(self) -> str:
        parts = self.merchant_id.split("|", 1)
        return parts[1].strip() if len(parts) > 1 else ""

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        nano = toman_to_nanoton(amount, self.rates().ton_toman)
        comment = ton_comment(payment_id)
        ton = format_ton(nano)
        # https, not ton://: Telegram refuses any other scheme on a button,
        # and the refusal takes the whole payment screen with it. Tonkeeper's
        # universal link opens whichever TON wallet the customer has.
        link = f"https://app.tonkeeper.com/transfer/{self.address}?amount={nano}&text={comment}"
        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            amount=amount,
            address=self.address,
            network="TON",
            redirect_url=link,
            instructions_fa=_address_text(
                coin="TON", amount=ton, address=self.address, toman=amount, comment=comment
            ),
            metadata={"gatewayReference": f"{comment}:{nano}", "cryptoAmount": ton},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        comment, _, nano_text = reference.partition(":")
        try:
            wanted = int(nano_text)
        except ValueError:
            logger.warning("ton.bad_reference", payment_id=payment_id, reference=reference)
            return _inconclusive(reference)
        params: dict[str, Any] = {"address": self.address, "limit": 100, "archival": "true"}
        if self.api_key:
            params["api_key"] = self.api_key
        try:
            body = _request("GET", f"{self.base_url}/getTransactions", params=params)
        except CryptoGatewayError as failure:
            logger.warning("ton.verify_failed", payment_id=payment_id, error=str(failure))
            return _inconclusive(reference)
        for transaction in body.get("result") or []:
            incoming = transaction.get("in_msg") if isinstance(transaction, dict) else None
            if not isinstance(incoming, dict):
                continue
            if str(incoming.get("message") or "").strip() != comment:
                continue
            try:
                value = int(incoming.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if value >= wanted:
                tx_id = transaction.get("transaction_id")
                tx_hash = tx_id.get("hash") if isinstance(tx_id, dict) else None
                return VerificationResult(
                    outcome=VerificationOutcome.CONFIRMED,
                    amount=expected,
                    reference=reference,
                    raw={"hash": tx_hash, "nanoton": value},
                )
            # Short: found, but not enough. An operator settles it by hand.
            logger.warning("ton.underpaid", payment_id=payment_id, got=value, wanted=wanted)
        return _inconclusive(reference)

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return _NO_ONLINE_REFUND


def ton_comment(payment_id: str) -> str:
    """Short enough to type by hand if a wallet drops the link's text."""
    cleaned = "".join(ch for ch in payment_id if ch.isalnum())
    return f"GV{cleaned[-10:].upper()}"


def format_ton(nano: int) -> str:
    text = f"{Decimal(nano) / Decimal(NANO_PER_TON):f}".rstrip("0").rstrip(".")
    return text or "0"


def _address_text(
    *, coin: str, amount: str, address: str, toman: Money, comment: str | None = None
) -> str:
    lines = [
        f"🪙 <b>پرداخت با {coin}</b>",
        "",
        f"💰 مبلغ دقیق: <code>{amount}</code> {coin}",
        f"(معادل {toman.amount:,} تومان)",
        "",
        "📮 آدرس:",
        f"<code>{address}</code>",
    ]
    if comment:
        lines += [
            "",
            f"📝 کامنت (Memo) — <b>حتماً بنویس</b>: <code>{comment}</code>",
            "بدون این کامنت پرداختت شناخته نمی‌شه.",
        ]
    lines += [
        "",
        "بعد از واریز، چند دقیقه طول می‌کشه تا شبکه تأیید کنه — "
        "خودکار تأیید می‌شه و همین‌جا خبرت می‌کنیم.",
    ]
    return "\n".join(lines)


__all__ = [
    "ADDRESS_CAPABILITIES",
    "REDIRECT_CAPABILITIES",
    "CryptoGatewayError",
    "ExchangeRates",
    "NowPaymentsGateway",
    "PlisioGateway",
    "TonGateway",
    "format_ton",
    "toman_to_nanoton",
    "toman_to_usd",
    "ton_comment",
]
