"""ZarinPal, Zibal and AqayePardakht.

Three providers, one shape, and the shape is `PaymentGateway` - so checkout,
the bot and the Mini App never learn a provider's name.

**The unit is the thing to get right.** This platform stores Toman. ZarinPal
and Zibal both take Rial; AqayePardakht takes Toman. A missing or a spurious
factor of ten is not a bug that looks like a bug - it is a customer charged a
tenth of the price, or ten times it, with every screen reporting success. So
the conversion lives on each adapter as a single named constant, and a test
pins all three against a known figure.

Verification is idempotent by construction on all three: they answer "already
verified" rather than failing, and every one of them is called by the callback
*and* by an operator pressing a button, sometimes at once.
"""

from __future__ import annotations

from dataclasses import dataclass
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

#: A payment page is a person waiting on a redirect. Short, and shorter than
#: the customer's patience rather than the provider's timeout.
TIMEOUT_SECONDS = 15.0

#: What every one of these can do. Auto-verified, redirect-based, and no online
#: refund: all three refund through their own panel on a settlement cycle, so
#: claiming otherwise here would promise a customer their money back in a way
#: the code cannot deliver.
ONLINE_CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=True,
    supports_online_refund=False,
    supports_partial_refund=False,
    requires_redirect=True,
    requires_manual_review=False,
)

#: Iranian banking quotes Rial; this platform stores Toman.
RIAL_PER_TOMAN: Final = 10


class GatewayCallFailed(RuntimeError):
    """The provider refused or could not be reached.

    One type for both, because the caller does the same thing either way -
    leave the payment unpaid and tell the customer to try again. Which of the
    two it was belongs in the log, not in the customer's message.
    """


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as failure:
        raise GatewayCallFailed(str(failure)) from failure
    try:
        body = response.json()
    except ValueError as failure:
        raise GatewayCallFailed(response.text[:200]) from failure
    if not isinstance(body, dict):
        raise GatewayCallFailed("The provider did not answer with an object.")
    return body


@dataclass(slots=True)
class ZarinPalGateway:
    """https://payment.zarinpal.com - v4 REST.

    Amounts in **Rial**.
    """

    merchant_id: str
    key: str = "zarinpal"
    title_fa: str = "درگاه زرین‌پال"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = ONLINE_CAPABILITIES
    base_url: str = "https://payment.zarinpal.com"

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        body = _post(
            f"{self.base_url}/pg/v4/payment/request.json",
            {
                "merchant_id": self.merchant_id,
                "amount": amount.amount * RIAL_PER_TOMAN,
                "callback_url": callback_url or "",
                "description": invoice_number,
            },
        )
        data = body.get("data") or {}
        authority = str(data.get("authority") or "")
        if not authority:
            logger.info("gateway.zarinpal.refused", detail=str(body.get("errors"))[:200])
            raise GatewayCallFailed("ZarinPal did not issue an authority.")

        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.GATEWAY,
            amount=amount,
            redirect_url=f"{self.base_url}/pg/StartPay/{authority}",
            # The authority is the reference the callback comes back with and
            # the one `verify` needs. It goes on the payment row.
            metadata={"authority": authority, "gateway": self.key},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        try:
            body = _post(
                f"{self.base_url}/pg/v4/payment/verify.json",
                {
                    "merchant_id": self.merchant_id,
                    "amount": expected.amount * RIAL_PER_TOMAN,
                    "authority": reference,
                },
            )
        except GatewayCallFailed as failure:
            # Unreachable is not "unpaid". Answering FAILED here would let a
            # sweeper cancel a payment the customer completed.
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE, message_fa=str(failure)[:200]
            )

        data = body.get("data") or {}
        code = int(data.get("code") or 0)
        # 100 is verified now, 101 is verified already. Both mean paid, and
        # treating 101 as a failure is how a retried callback reverses a
        # successful payment.
        if code in (100, 101):
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED,
                reference=str(data.get("ref_id") or reference),
                amount=expected,
            )
        return VerificationResult(
            outcome=VerificationOutcome.DECLINED, message_fa=f"ZarinPal code {code}"
        )

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        """Declines, so the caller falls back to the wallet.

        ZarinPal refunds run on a settlement cycle from their own panel. A
        `True` here would tell a customer their money is on its way back when
        nothing has been asked of anybody.
        """
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa="بازگشت وجه این درگاه به کیف پول انجام می‌شود.",
        )


@dataclass(slots=True)
class ZibalGateway:
    """https://gateway.zibal.ir - v1.

    Amounts in **Rial**.
    """

    merchant_id: str
    key: str = "zibal"
    title_fa: str = "درگاه زیبال"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = ONLINE_CAPABILITIES
    base_url: str = "https://gateway.zibal.ir"

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        body = _post(
            f"{self.base_url}/v1/request",
            {
                "merchant": self.merchant_id,
                "amount": amount.amount * RIAL_PER_TOMAN,
                "callbackUrl": callback_url or "",
                "description": invoice_number,
                "orderId": payment_id,
            },
        )
        if int(body.get("result") or 0) != 100 or not body.get("trackId"):
            logger.info("gateway.zibal.refused", detail=str(body.get("message"))[:200])
            raise GatewayCallFailed("Zibal did not issue a track id.")

        track_id = str(body["trackId"])
        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.GATEWAY,
            amount=amount,
            redirect_url=f"{self.base_url}/start/{track_id}",
            metadata={"authority": track_id, "gateway": self.key},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        try:
            body = _post(
                f"{self.base_url}/v1/verify",
                {"merchant": self.merchant_id, "trackId": reference},
            )
        except GatewayCallFailed as failure:
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE, message_fa=str(failure)[:200]
            )

        result = int(body.get("result") or 0)
        # 100 verified, 201 already verified.
        if result in (100, 201):
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED,
                reference=str(body.get("refNumber") or reference),
                amount=expected,
            )
        return VerificationResult(
            outcome=VerificationOutcome.DECLINED, message_fa=f"Zibal result {result}"
        )

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa="بازگشت وجه این درگاه به کیف پول انجام می‌شود.",
        )


@dataclass(slots=True)
class AqayePardakhtGateway:
    """https://panel.aqayepardakht.ir - v2.

    Amounts in **Toman**, unlike the other two. That difference is the single
    most dangerous line in this file: the same number sent to the wrong
    provider is a customer charged ten times or a tenth.
    """

    merchant_id: str
    key: str = "aqayepardakht"
    title_fa: str = "درگاه آقای پرداخت"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = ONLINE_CAPABILITIES
    base_url: str = "https://panel.aqayepardakht.ir"

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        body = _post(
            f"{self.base_url}/api/v2/create",
            {
                "pin": self.merchant_id,
                # Toman. No conversion, and the absence is deliberate.
                "amount": amount.amount,
                "callback": callback_url or "",
                "invoice_id": invoice_number,
            },
        )
        transaction = str(body.get("transid") or "")
        if str(body.get("status") or "") != "success" or not transaction:
            logger.info("gateway.aqayepardakht.refused", detail=str(body.get("code"))[:200])
            raise GatewayCallFailed("AqayePardakht did not issue a transaction id.")

        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.GATEWAY,
            amount=amount,
            redirect_url=f"{self.base_url}/startpay/{transaction}",
            metadata={"authority": transaction, "gateway": self.key},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        try:
            body = _post(
                f"{self.base_url}/api/v2/verify",
                {
                    "pin": self.merchant_id,
                    "amount": expected.amount,
                    "transid": reference,
                },
            )
        except GatewayCallFailed as failure:
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE, message_fa=str(failure)[:200]
            )

        code = str(body.get("code") or "")
        # "1" verified, "2" already verified.
        if code in ("1", "2"):
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED, reference=reference, amount=expected
            )
        return VerificationResult(
            outcome=VerificationOutcome.DECLINED, message_fa=f"AqayePardakht code {code}"
        )

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa="بازگشت وجه این درگاه به کیف پول انجام می‌شود.",
        )


#: Every provider this platform can be configured with, by the key stored on a
#: payment row. Keys are persisted forever, so none may ever be renamed.
BUILDERS: Final[dict[str, type]] = {
    "zarinpal": ZarinPalGateway,
    "zibal": ZibalGateway,
    "aqayepardakht": AqayePardakhtGateway,
}


def build(provider: str, merchant_id: str) -> Any:
    return BUILDERS[provider](merchant_id=merchant_id)


__all__ = [
    "BUILDERS",
    "ONLINE_CAPABILITIES",
    "RIAL_PER_TOMAN",
    "AqayePardakhtGateway",
    "GatewayCallFailed",
    "ZarinPalGateway",
    "ZibalGateway",
    "build",
]
