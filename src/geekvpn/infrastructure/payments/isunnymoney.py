"""iSunnyMoney (Nabik): a redirect gateway, settled by asking.

`POST /request` returns an authority and a payment link; the customer pays at
the bank and comes back to our callback; `POST /verify` with the authority
says whether it was paid. JSON only - form data mangles `order_id`. Amounts
are Toman (`IRT`), like this platform, so there is no conversion to get wrong.

**The order id** is an integer the gateway insists on (a string is refused),
must be unique (a repeat is refused as a duplicate), and is clamped to the
32-bit limit - a larger one silently becomes 2147483647, after which every
payment collides. So it comes from a database sequence that starts at 100001
and stops at that limit, and a value past it is refused here, before the
gateway can clamp it.

**No payment is left hanging.** The operator's requirement, and the reason
for the two clocks below. Every payment ends one of three ways:

* paid -> confirmed (a short amount is escalated by the verification service);
* refused by the gateway, or still unpaid after `PAYMENT_WINDOW` -> declined;
* no readable answer at all for `GIVE_UP_AFTER` -> handed to a person, with an
  alert. Declining would be wrong - it may have been paid - and waiting for
  ever is exactly what was ruled out.

`verify` is told only the reference and the expected amount, so the
authority, the order id and when the payment started all travel in the
reference: `"<authority>:<order_id>:<epoch>"`.
"""

from __future__ import annotations

from collections.abc import Callable
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
from geekvpn.infrastructure.outbound_proxy import proxy_for

logger = get_logger(__name__)

BASE_URL: Final = "https://core.isunnymoney.com"
TIMEOUT_SECONDS: Final = 15.0
#: Anything but httpx's default. The gateway's firewall answers 403 to a
#: `python-httpx/x` User-Agent before the request reaches iSunnyMoney at all,
#: so every checkout failed with an HTML "Forbidden" page; curl's passed.
USER_AGENT: Final = "GeekVPN/1.0"
#: The largest order id the gateway keeps as given.
MAX_ORDER_ID: Final = 2_147_483_647

#: Unpaid this long after starting means it will not be: the bank's own
#: session is long gone. Declined, so the order is closed rather than open.
PAYMENT_WINDOW: Final = timedelta(minutes=60)
#: No readable answer for this long, and a person decides.
GIVE_UP_AFTER: Final = timedelta(hours=6)
#: The worker asks every half minute anyway; this is a hint, not a promise.
RETRY_AFTER: Final = timedelta(seconds=30)

PAID: Final = frozenset({"paid", "100", "success", "verified"})
DEAD: Final = frozenset(
    {"failed", "fail", "canceled", "cancelled", "expired", "rejected", "unpaid", "error"}
)

CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=True,
    supports_online_refund=False,
    supports_partial_refund=False,
    requires_redirect=True,
    requires_manual_review=False,
)


class IsunnyMoneyError(RuntimeError):
    """Refused, unreachable, or unreadable."""


def _no_sequence() -> int:
    raise IsunnyMoneyError("No order-id sequence was given to this gateway.")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class IsunnyMoneyGateway:
    merchant_id: str
    """The merchant key from the iSunnyMoney panel."""

    #: The next order id, from the database sequence. See the module docstring.
    next_order_id: Callable[[], int] = _no_sequence
    now: Callable[[], datetime] = _utc_now
    base_url: str = BASE_URL
    key: str = "isunnymoney"
    title_fa: str = "پرداخت آنلاین (درگاه بانکی)"
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
        if not callback_url:
            # Without it the bank has nowhere to send the customer back, and
            # the payment can only be settled by the sweep.
            raise IsunnyMoneyError("The gateway needs a callback address.")
        order_id = self.next_order_id()
        if not 0 < order_id <= MAX_ORDER_ID:
            raise IsunnyMoneyError(f"Order id {order_id} is outside what the gateway keeps.")
        started = self.now()
        body = self._call(
            "/request",
            {
                "amount": amount.amount,
                "currency": "IRT",
                "merchant": self.merchant_id,
                "order_id": order_id,
                "callback": callback_url,
                "description": f"فاکتور {invoice_number}",
            },
        )
        data = _data(body)
        if body.get("success") is not True:
            raise IsunnyMoneyError(_message(body) or "The gateway refused the payment request.")
        authority = data.get("authority")
        link = str(data.get("payment_link") or "")
        if not authority or not link:
            raise IsunnyMoneyError("The request answered no authority or payment link.")
        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            amount=amount,
            redirect_url=link,
            metadata={
                "gatewayReference": f"{authority}:{order_id}:{int(started.timestamp())}",
                "isunnyOrderId": str(order_id),
            },
        )

    # -- verification ------------------------------------------------------

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        parsed = _parse(reference)
        if parsed is None:
            # Nothing to ask about, and no clock to wait out: a person.
            logger.warning("isunny.bad_reference", payment_id=payment_id, reference=reference)
            return self._to_person(reference, "شناسهٔ پرداخت درگاه خوانا نبود.")
        authority, started = parsed
        age = self.now() - started

        try:
            body = self._call("/verify", {"authority": authority, "merchant": self.merchant_id})
        except IsunnyMoneyError as failure:
            logger.warning("isunny.verify_failed", payment_id=payment_id, error=str(failure))
            return self._unanswered(reference, age)

        data = _data(body)
        status = str(data.get("status") or "").strip().lower()
        gateway_status = str(data.get("gateway_status") or "").strip()

        if status in PAID or gateway_status == "100":
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED,
                # What the gateway says arrived; a shortfall is escalated by
                # the verification service, never delivered.
                amount=_money(data.get("amount"), fallback=expected),
                reference=reference,
                raw={
                    "status": status,
                    "trans_id": data.get("trans_id"),
                    "card_number": data.get("card_number"),
                },
            )
        if status in DEAD:
            return VerificationResult(
                outcome=VerificationOutcome.DECLINED,
                reference=reference,
                raw={"status": status},
                message_fa="پرداخت انجام نشد. چیزی از حسابت کم نشده.",
            )
        if status == "pending":
            if age > PAYMENT_WINDOW:
                return VerificationResult(
                    outcome=VerificationOutcome.DECLINED,
                    reference=reference,
                    raw={"status": status},
                    message_fa="مهلت پرداخت تموم شد. اگه مبلغی کم شده، خودکار برمی‌گرده.",
                )
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE,
                reference=reference,
                raw={"status": status},
                retry_after=RETRY_AFTER,
            )
        # Neither paid, nor dead, nor pending: an answer we cannot read.
        logger.warning(
            "isunny.unreadable_verify", payment_id=payment_id, message=_message(body) or status
        )
        return self._unanswered(reference, age)

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa="بازگشت وجه این درگاه به کیف پول انجام می‌شه.",
        )

    # -- helpers -----------------------------------------------------------

    def _unanswered(self, reference: str, age: timedelta) -> VerificationResult:
        if age > GIVE_UP_AFTER:
            return self._to_person(
                reference, "درگاه چند ساعت جواب روشنی نداد؛ پرداخت به بررسی ادمین رفت."
            )
        return VerificationResult(
            outcome=VerificationOutcome.INCONCLUSIVE, reference=reference, retry_after=RETRY_AFTER
        )

    @staticmethod
    def _to_person(reference: str, why: str) -> VerificationResult:
        return VerificationResult(
            outcome=VerificationOutcome.MISMATCH, reference=reference, message_fa=why
        )

    def _call(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.request(
                "POST",
                f"{self.base_url}{path}",
                json=payload,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
                proxy=proxy_for(self.base_url),
            )
        except httpx.HTTPError as failure:
            raise IsunnyMoneyError(str(failure) or type(failure).__name__) from failure
        try:
            body = response.json()
        except ValueError as failure:
            # The status first: a firewall's HTML page is otherwise hard to
            # tell apart from the gateway itself misbehaving.
            raise IsunnyMoneyError(
                f"HTTP {response.status_code}: {response.text[:200]}"
            ) from failure
        if not isinstance(body, dict):
            raise IsunnyMoneyError("The gateway did not answer with an object.")
        if response.status_code >= 500:
            raise IsunnyMoneyError(_message(body) or str(response.status_code))
        return body


def _parse(reference: str) -> tuple[int, datetime] | None:
    parts = reference.split(":")
    if len(parts) != 3:
        return None
    try:
        authority = int(parts[0])
        started = datetime.fromtimestamp(int(parts[2]), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None
    return (authority, started) if authority > 0 else None


def _data(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def _money(value: Any, *, fallback: Money) -> Money:
    """Never zero by accident: a missing amount must not settle against nothing."""
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return fallback
    return Money(amount) if amount > 0 else fallback


def _message(body: dict[str, Any]) -> str:
    message = body.get("message")
    if message:
        return str(message)
    data = body.get("data")
    if isinstance(data, list):
        return "; ".join(
            str(item.get("error") or "") for item in data if isinstance(item, dict)
        ).strip("; ")
    return ""


__all__ = [
    "BASE_URL",
    "CAPABILITIES",
    "GIVE_UP_AFTER",
    "MAX_ORDER_ID",
    "PAYMENT_WINDOW",
    "IsunnyMoneyError",
    "IsunnyMoneyGateway",
]
