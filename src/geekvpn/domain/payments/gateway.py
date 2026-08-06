"""The gateway seam.

Today GeekVPN takes card-to-card and crypto, both approved by hand. Online
gateways (Zarinpal, NextPay, IDPay, a crypto processor) come later. This
module is what makes "later" cheap.

The design rule: **a gateway is data plus a protocol, never a subclass of
anything in the domain.** ``PaymentMethod.GATEWAY`` is a single enum member
and the provider is a string key, so adding Zarinpal is a registry entry and
an adapter class - no enum migration, no change to ``Payment``, no new state.

The second rule: **the domain declares the interface, infrastructure
implements it.** These Protocols are structural, so an adapter in the
infrastructure layer satisfies them without importing a base class, and the
domain never learns what HTTP is.

The manual methods implement the same protocol as a real gateway. That is
deliberate: if card-to-card is just "a gateway whose verification is a human",
then the day a real gateway arrives, the checkout flow above it does not
change at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Protocol, runtime_checkable

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    RefundDestination,
    VerificationOutcome,
)
from geekvpn.domain.payments.errors import GatewayNotRegistered


@dataclass(frozen=True, slots=True, kw_only=True)
class GatewayCapabilities:
    """What a provider can actually do.

    Checkout reads these instead of hard-coding provider names. "Can I offer
    an instant refund for this payment?" must be answerable without a chain of
    ``if gateway == ...``, or every new provider becomes a code hunt.
    """

    supports_auto_verification: bool
    supports_online_refund: bool
    supports_partial_refund: bool
    requires_redirect: bool
    requires_manual_review: bool
    settlement_delay: timedelta = timedelta()
    """How long after approval the money is really ours. Card-to-card is
    instant; a gateway may settle T+1. Refund policy reads this."""

    min_amount: int = 0
    max_amount: int | None = None

    def accepts(self, amount: Money) -> bool:
        if amount.amount < self.min_amount:
            return False
        return self.max_amount is None or amount.amount <= self.max_amount


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckoutInstruction:
    """What the customer must do next.

    One type covers every method, which is what keeps the bot and the Mini App
    free of provider branching:

    * card       -> ``instructions_fa`` holds the card number and holder name
    * crypto     -> ``address`` and ``network``
    * gateway    -> ``redirect_url``
    * wallet     -> nothing; already settled
    """

    payment_id: str
    method: PaymentMethod
    amount: Money
    expires_at: datetime | None = None
    redirect_url: str | None = None
    address: str | None = None
    network: str | None = None
    instructions_fa: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def needs_customer_action(self) -> bool:
        return self.method is not PaymentMethod.WALLET


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationResult:
    """The answer to "did this payment really happen?".

    ``INCONCLUSIVE`` is a first-class outcome, not an error. A crypto transfer
    with one confirmation is neither settled nor false, and a verifier forced
    to answer yes/no about it will answer wrongly. ``retry_after`` tells the
    scheduler when to ask again.
    """

    outcome: VerificationOutcome
    amount: Money | None = None
    reference: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    message_fa: str | None = None
    retry_after: timedelta | None = None

    @property
    def confirmed(self) -> bool:
        return self.outcome is VerificationOutcome.CONFIRMED

    @property
    def should_retry(self) -> bool:
        return self.outcome is VerificationOutcome.INCONCLUSIVE


@dataclass(frozen=True, slots=True, kw_only=True)
class RefundResult:
    """What a provider did with a refund request."""

    succeeded: bool
    destination: RefundDestination
    reference: str | None = None
    message_fa: str | None = None


@runtime_checkable
class PaymentGateway(Protocol):
    """Everything the application layer needs from a way of taking money.

    Implemented by the manual card and crypto adapters today and by real
    providers later. The application layer talks only to this.
    """

    key: str
    """Stable identifier stored on the payment row, e.g. ``"card"`` or
    ``"zarinpal"``. Persisted forever, so it must never be renamed."""

    title_fa: str
    method: PaymentMethod
    capabilities: GatewayCapabilities

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        """Start the attempt and say what the customer must do next."""
        ...

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        """Ask the provider whether the money arrived.

        Must be **idempotent**: it is called by the callback, by the polling
        sweeper, and by an admin pressing a button, possibly at once.
        """
        ...

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        """Return money through the provider.

        Adapters that cannot do this return ``succeeded=False`` with
        ``destination=WALLET`` rather than raising, so the caller falls back to
        a wallet credit instead of failing the refund entirely.
        """
        ...


MANUAL_CAPABILITIES: Final[GatewayCapabilities] = GatewayCapabilities(
    supports_auto_verification=False,
    supports_online_refund=False,
    supports_partial_refund=True,
    requires_redirect=False,
    requires_manual_review=True,
)
"""Card-to-card and crypto today: a human verifies, refunds go to the wallet.

Partial refunds are still supported because they are a bookkeeping operation
on our side, not something the bank has to agree to.
"""


class GatewayRegistry:
    """The lookup table checkout uses to find a gateway by key.

    A registry rather than a match statement so that enabling a provider is a
    configuration change. ``available_for`` is what the bot calls to build the
    payment-method keyboard, which means a provider that is registered but
    over its limit for this basket simply does not appear - no dead button
    that fails after the customer taps it.
    """

    __slots__ = ("_gateways",)

    def __init__(self) -> None:
        self._gateways: dict[str, PaymentGateway] = {}

    def register(self, gateway: PaymentGateway) -> None:
        self._gateways[gateway.key] = gateway

    def get(self, key: str) -> PaymentGateway:
        try:
            return self._gateways[key]
        except KeyError as error:
            raise GatewayNotRegistered(
                "No payment gateway is registered under that key.", key=key
            ) from error

    def has(self, key: str) -> bool:
        return key in self._gateways

    def all(self) -> tuple[PaymentGateway, ...]:
        return tuple(self._gateways.values())

    def for_method(self, method: PaymentMethod) -> tuple[PaymentGateway, ...]:
        return tuple(gateway for gateway in self._gateways.values() if gateway.method is method)

    def available_for(self, amount: Money) -> tuple[PaymentGateway, ...]:
        """Only the gateways that will actually accept this amount."""
        return tuple(
            gateway for gateway in self._gateways.values() if gateway.capabilities.accepts(amount)
        )


__all__ = [
    "MANUAL_CAPABILITIES",
    "CheckoutInstruction",
    "GatewayCapabilities",
    "GatewayRegistry",
    "PaymentGateway",
    "RefundResult",
    "VerificationResult",
]
