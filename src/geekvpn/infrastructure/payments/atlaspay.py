"""AtlasPay — card-to-card with automatic SMS confirmation.

Shaped like the other online gateways so checkout, the bot and the Mini App
never learn its name, but it works differently from all three of them in ways
that matter:

**There is no callback.** AtlasPay never calls us. Confirmation arrives only by
asking, which is exactly what `VerificationService` already does on a schedule -
so this adapter needs no webhook, no public endpoint and no signature check. It
answers `INCONCLUSIVE` until the order settles, and the existing sweeper does
the rest.

**The customer pays a different number than we quoted.** AtlasPay adds a few
Toman to the price so its SMS matcher can tell one transfer from another, and
returns the result as `totalAmountToman`. Showing our own figure instead would
produce a transfer that never matches, so the instruction carries theirs.

**The card can be shown in our own bot.** With the direct-display feature
enabled on the merchant account, the create response carries the full card
number, holder and bank - so the customer sees them in our chat and never opens
anybody else's bot. The mini-app link is still handed over, because it is the
only way to upload a receipt when the automatic matcher does not fire, and a
payment page with no fallback is a customer with nowhere to go.

The card number is put in front of the customer and deliberately not stored:
`instructions_fa` is rendered and discarded, and `metadata` keeps only the
order id, the tracking code and the amount. AtlasPay's own guidance is to hold
it briefly or not at all, and not at all is easier to be sure of.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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

BASE_URL: Final = "https://api.atlaspay.space/api/v1"

#: A person is waiting on this call with a payment screen half-drawn.
TIMEOUT_SECONDS: Final = 15.0

#: Their window, not ours. Quoted in the docs as twenty minutes from creation,
#: and used only as a fallback when the response does not carry the deadline.
PAYMENT_WINDOW: Final = timedelta(minutes=20)

#: How long before the sweeper asks again. Their matcher settles in seconds
#: when the SMS arrives, and a receipt needs a person, so this is a compromise
#: between a customer staring at a screen and a pointless request per second.
RETRY_AFTER: Final = timedelta(seconds=20)

#: Their vocabulary. Anything not named here is "still in progress", which is
#: the safe reading: a status we do not recognise must never be read as a
#: refusal, because that fails a payment that may yet succeed.
SETTLED: Final = frozenset({"confirmed", "settled"})
DEAD: Final = frozenset({"rejected", "expired", "cancelled"})

CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=True,
    supports_online_refund=False,
    supports_partial_refund=False,
    # False on purpose. The customer is not redirected anywhere: they read the
    # card in our chat and transfer from their banking app. The mini-app link
    # is a fallback for uploading a receipt, not the route.
    requires_redirect=False,
    requires_manual_review=False,
)


class AtlasPayError(RuntimeError):
    """Refused, unreachable, or unreadable - the caller does the same thing."""


@dataclass(slots=True)
class AtlasPayGateway:
    """https://api.atlaspay.space - amounts in **Toman**, like this platform."""

    merchant_id: str
    """The API key. Named `merchant_id` because that is the column every
    gateway account stores its credential in, and it is encrypted there."""

    base_url: str = BASE_URL
    key: str = "atlaspay"
    #: Names the difference a customer can act on, not the mechanism.
    #:
    #: "کارت به کارت خودکار" sat directly under the manual "کارت به کارت" and
    #: read as a duplicate of it - the operator who configured this provider
    #: looked at their own bot and reported the button missing. The thing that
    #: is actually different is the wait: seconds here, up to half an hour
    #: through the review queue.
    title_fa: str = "کارت به کارت (تأیید فوری)"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = field(default_factory=lambda: CAPABILITIES)

    # -- checkout ----------------------------------------------------------

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        body = self._call(
            "POST",
            "/orders",
            {
                "merchantOrderRef": payment_id,
                "baseAmountToman": amount.amount,
                # Ties the order to this customer inside their mini app, so it
                # opens on the right payment rather than asking them to find it.
                "customerTelegramId": user_id,
            },
        )

        order_id = body.get("orderId")
        if order_id is None:
            raise AtlasPayError("The create response carried no order id.")

        total = _as_money(body.get("totalAmountToman"), fallback=amount)
        link = str(body.get("customerStartLink") or "")

        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            # Theirs, not ours. See the module docstring: a transfer of our
            # figure is a transfer their matcher never recognises.
            amount=total,
            expires_at=_deadline(body.get("paymentDeadlineAt")),
            redirect_url=link or None,
            instructions_fa=_card_text(body, total=total, link=link),
            metadata={
                # What `verify` needs. Everything else here is for an operator
                # reading a payment row during a support conversation - and the
                # card number is deliberately not among it.
                "gatewayReference": str(order_id),
                "atlaspayTracking": str(body.get("trackingCode") or ""),
                "atlaspayTotalToman": str(total.amount),
            },
        )

    # -- verification ------------------------------------------------------

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        """Ask whether the transfer arrived.

        `reference` is their order id, which checkout stored from the
        instruction's metadata. Without it there is nothing to ask about, and
        answering "declined" would fail a payment that may be perfectly fine -
        so an empty reference is inconclusive, and loudly.
        """
        if not reference:
            logger.warning("atlaspay.no_reference", payment_id=payment_id)
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE, retry_after=RETRY_AFTER
            )

        try:
            body = self._call("POST", f"/orders/{reference}/verify", {})
        except AtlasPayError as failure:
            # Unreachable is not declined. Asking again costs one request; a
            # wrong "declined" costs a customer their money.
            logger.warning("atlaspay.verify_failed", payment_id=payment_id, error=str(failure))
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE, retry_after=RETRY_AFTER
            )

        status = str(body.get("status") or "").lower()
        paid = body.get("paid")
        settled = paid is True or status in SETTLED

        if settled:
            # What actually arrived, when they say - underpayment they resolved
            # in the customer's favour lands here as a smaller figure, and the
            # verification service compares it against the invoice itself.
            received = _as_money(
                body.get("actualReceivedAmountToman"),
                fallback=_as_money(body.get("totalAmountToman"), fallback=expected),
            )
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED,
                amount=received,
                reference=reference,
                raw={"status": status},
            )

        if status in DEAD:
            return VerificationResult(
                outcome=VerificationOutcome.DECLINED,
                reference=reference,
                raw={"status": status},
                message_fa=_DEAD_FA.get(status, "پرداخت انجام نشد."),
            )

        return VerificationResult(
            outcome=VerificationOutcome.INCONCLUSIVE,
            reference=reference,
            raw={"status": status},
            retry_after=RETRY_AFTER,
        )

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        """Not offered. Settlement is in TRX to the merchant's own wallet, so
        there is nothing to reverse through this API - the refund goes to the
        customer's wallet here, which is what `succeeded=False` asks for."""
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa="بازگشت وجه این درگاه به کیف پول انجام می‌شه.",
        )

    # -- transport ---------------------------------------------------------

    def _call(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                headers={"X-API-Key": self.merchant_id},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as failure:
            raise AtlasPayError(str(failure)) from failure

        try:
            body = response.json()
        except ValueError as failure:
            raise AtlasPayError(response.text[:200]) from failure
        if not isinstance(body, dict):
            raise AtlasPayError("AtlasPay did not answer with an object.")
        if response.status_code >= 400 or body.get("success") is False:
            raise AtlasPayError(str(body.get("message") or response.status_code))
        return body


_DEAD_FA: Final[dict[str, str]] = {
    "expired": "مهلت پرداخت تموم شد. یه سفارش تازه بزن.",
    "cancelled": "این پرداخت لغو شد.",
    "rejected": "پرداخت تأیید نشد. اگه واریز کردی، رسیدت رو به پشتیبانی بده.",
}


def _as_money(value: Any, *, fallback: Money) -> Money:
    """Their figure, or ours when they did not send one.

    Never zero by accident: a missing amount that read as zero would settle a
    payment against nothing at all.
    """
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return fallback
    return Money(amount) if amount > 0 else fallback


def _deadline(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return datetime.now(UTC) + PAYMENT_WINDOW
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC) + PAYMENT_WINDOW
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _card_text(body: dict[str, Any], *, total: Money, link: str) -> str:
    """What the customer reads in our own chat.

    The full card is only present when AtlasPay has enabled direct display for
    this merchant. Without it there is nothing to show and the mini app is the
    whole flow, so the text says that rather than drawing an empty card.
    """
    card = str(body.get("cardNumber") or "").strip()
    if not card:
        return (
            "برای دیدن شمارهٔ کارت و پرداخت، دکمهٔ زیر رو بزن.\n\n"
            f"💰 مبلغ دقیق: {total.amount:,} تومان\n"
            "⚠️ مبلغ رو رند نکن — رقم‌های آخرش شناسهٔ همین پرداخته."
        )

    holder = str(body.get("cardHolderName") or "").strip()
    bank = str(body.get("bankName") or "").strip()
    lines = [
        "💳 <b>پرداخت کارت به کارت</b>",
        "",
        f"💰 مبلغ: <b>{total.amount:,}</b> تومان",
        f"🔢 برای کپی: <code>{total.amount}</code>",
        "",
        f"💳 <code>{card}</code>",
    ]
    if holder:
        lines.append(f"👤 به نام: {holder}")
    if bank:
        lines.append(f"🏦 بانک: {bank}")
    lines += [
        "",
        "⚠️ <b>مبلغ رو رند نکن.</b> رقم‌های آخرش شناسهٔ همین پرداخته و "
        "رسیدت با همون شناخته می‌شه.",
        "",
        "بعد از واریز حدود ۲ دقیقه صبر کن — معمولاً خودکار تأیید می‌شه و "
        "همین‌جا خبرت می‌کنیم.",
    ]
    if link:
        lines.append("اگه خودکار تأیید نشد، از دکمهٔ زیر رسیدت رو بفرست.")
    return "\n".join(lines)


__all__ = ["BASE_URL", "CAPABILITIES", "AtlasPayError", "AtlasPayGateway"]
