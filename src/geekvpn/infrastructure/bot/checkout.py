"""The bot's ``CheckoutService`` port, over the real payment services.

This is the only adapter that moves money, so it is the one worth reading twice.

The shapes on either side are genuinely different, and the difference is not
cosmetic. The bot asks "start a card payment for this plan"; the payment service
asks for an invoice with itemised lines and a gateway key. Turning the first
into the second means pricing the plan and recording an order, so this adapter
performs three steps in a fixed order:

1. **Quote** the plan asynchronously, so the customer is charged today's price
   with today's discounts.
2. **Place an order**, because provisioning is driven by the order and an
   approved payment with no order behind it is money taken for nothing.
3. **Begin the payment** synchronously and stamp the resulting invoice id back
   onto the order, which is the link ``OrderPaymentBridge`` follows when the
   payment is later approved.

If step 3 fails the order stays PENDING and unpaid, which is the safe direction
to fail in: a customer with an abandoned order is a support question, a payment
with no order is a refund.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.bot.read_models import (
    CardPaymentDetails,
    CryptoPaymentDetails,
    PendingPayment,
    SubscriptionCard,
)
from geekvpn.application.bot.read_models import (
    PaymentMethod as CardMethod,
)
from geekvpn.application.bot.read_models import (
    PaymentState as CardPaymentState,
)
from geekvpn.application.catalog.quoting_service import QuotingService
from geekvpn.application.payments.checkout_service import CheckoutRequest, CheckoutResult
from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.order_service import OrderService
from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.pricing import PriceQuote
from geekvpn.domain.payments.enums import PaymentMethod, PaymentState
from geekvpn.domain.payments.invoice import InvoiceLine
from geekvpn.domain.payments.proof import PaymentProof
from geekvpn.domain.provisioning.errors import DeliveryPending
from geekvpn.domain.provisioning.order import Order
from geekvpn.infrastructure.bot.readers import to_card
from geekvpn.infrastructure.bot.sync_readers import SyncBridge
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.persistence.repositories.catalog import (
    SqlAlchemyCouponRepository,
    SqlAlchemyPlanRepository,
)
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SqlAlchemyOrderRepository,
)

#: MiB per GiB; plans are sold in GiB and orders record MiB.
MIB_PER_GIB = 1024

#: Gateway keys, matching the adapters in ``application/payments/adapters.py``.
CARD = "card"
CRYPTO = "crypto"
WALLET = "wallet"

_CARD_STATE: dict[PaymentState, CardPaymentState] = {
    PaymentState.AWAITING_PROOF: CardPaymentState.AWAITING_PROOF,
    PaymentState.PENDING_REVIEW: CardPaymentState.PENDING_REVIEW,
    PaymentState.APPROVED: CardPaymentState.APPROVED,
    PaymentState.REJECTED: CardPaymentState.REJECTED,
}

_CARD_METHOD: dict[PaymentMethod, CardMethod] = {
    PaymentMethod.CARD: CardMethod.CARD,
    PaymentMethod.CRYPTO: CardMethod.CRYPTO,
    PaymentMethod.WALLET: CardMethod.WALLET,
}


class BotCheckoutAdapter:
    """Implements the bot's ``CheckoutService`` port."""

    def __init__(
        self,
        *,
        bridge: SyncBridge,
        quoting: QuotingService,
        orders: OrderService,
        order_repository: SqlAlchemyOrderRepository,
        provisioning: ProvisioningService,
        session: AsyncSession,
        plans: SqlAlchemyPlanRepository,
        coupons: SqlAlchemyCouponRepository,
        clock: Clock,
        jalali_year: int,
        crypto_network: str = "TRC20",
        #: Downloads a Telegram file so its bytes can be fingerprinted. Optional
        #: only so the adapter stays constructible in tests; `attach_receipt`
        #: refuses rather than falling back to hashing the file id.
        fetch_receipt: Callable[[str], Awaitable[bytes]] | None = None,
    ) -> None:
        self._bridge = bridge
        self._quoting = quoting
        self._orders = orders
        self._order_repository = order_repository
        self._provisioning = provisioning
        self._session = session
        self._plans = plans
        self._coupons = coupons
        self._clock = clock
        self._jalali_year = jalali_year
        self._crypto_network = crypto_network
        self._fetch_receipt = fetch_receipt

    # -- buying a plan -----------------------------------------------------

    async def pay_from_wallet(
        self, user_id: uuid.UUID, *, plan_id: uuid.UUID, coupon_code: str | None = None
    ) -> SubscriptionCard:
        """Debit the wallet and deliver the service in one call.

        Unlike card and crypto there is no proof step: the wallet gateway
        settles inside ``begin``, the sync scope publishes ``PaymentApproved``,
        and ``OrderPaymentBridge`` moves the order to PAID before that
        transaction commits. Provisioning then runs here, so what the customer
        waits for is the panel rather than a reviewer.
        """
        _, order = await self._begin(user_id, plan_id, coupon_code, gateway_key=WALLET)

        # The order was marked PAID by the *other* scope. This session created
        # it moments ago and still holds the PENDING copy in its identity map,
        # so `provision` would read a stale state and refuse. Expiring is what
        # forces the re-read; without it wallet checkout fails every time.
        self._session.expire_all()

        try:
            subscription = await self._provisioning.provision(order.id)
        except Exception as failure:
            # The money is ours and the order says so. Persist whatever state
            # provisioning reached - it marks the order FAILED for the retry
            # queue - and tell the customer the truth instead of the generic
            # apology, which reads as "your payment vanished".
            await self._session.commit()
            # `from failure`, never `from None`. Suppressing the cause here
            # produced a log line containing only this apology - the one thing
            # already visible on the customer's screen - and threw away the
            # panel error underneath it, which is the only part worth keeping.
            raise DeliveryPending(
                "پرداخت شما انجام شد، ولی ساخت اکانت هنوز کامل نشده است. "
                "پشتیبانی در جریان است و سرویس به‌زودی فعال می‌شود.",
                order_id=order.id,
            ) from failure

        return to_card(subscription, order)

    async def begin_card(
        self, user_id: uuid.UUID, *, plan_id: uuid.UUID, coupon_code: str | None = None
    ) -> CardPaymentDetails:
        result, _ = await self._begin(user_id, plan_id, coupon_code, gateway_key=CARD)
        gateway = await self._bridge.run(lambda scope: scope.gateways.get(CARD))
        return CardPaymentDetails(
            card_number=getattr(gateway, "card_number", ""),
            card_holder_fa=getattr(gateway, "card_holder_fa", ""),
            bank_fa=getattr(gateway, "bank_name_fa", ""),
            review_sla_fa=_REVIEW_SLA_FA,
            payment=_to_pending(result),
        )

    async def begin_crypto(
        self, user_id: uuid.UUID, *, plan_id: uuid.UUID, coupon_code: str | None = None
    ) -> CryptoPaymentDetails:
        result, _ = await self._begin(user_id, plan_id, coupon_code, gateway_key=CRYPTO)
        return CryptoPaymentDetails(
            network=result.instruction.network or "",
            asset=result.instruction.network or "",
            amount_display=str(result.instruction.amount.amount),
            address=result.instruction.address or "",
            payment=_to_pending(result),
        )

    # -- topping up --------------------------------------------------------

    async def begin_topup(
        self, user_id: uuid.UUID, *, amount: int, method: str
    ) -> CardPaymentDetails | CryptoPaymentDetails:
        """No order is placed: a top-up buys nothing, it moves money inward."""
        telegram_id = await self._require_telegram_id(user_id)
        year = self._jalali_year

        def work(scope: SyncScope) -> CheckoutResult:
            return scope.checkout.begin_topup(
                user_id=telegram_id,
                amount=Money(amount),
                gateway_key=method,
                jalali_year=year,
            )

        result = await self._bridge.run(work)
        if method == CRYPTO:
            return CryptoPaymentDetails(
                network=result.instruction.network or "",
                asset=result.instruction.network or "",
                amount_display=str(result.instruction.amount.amount),
                address=result.instruction.address or "",
                payment=_to_pending(result),
            )
        gateway = await self._bridge.run(lambda scope: scope.gateways.get(CARD))
        return CardPaymentDetails(
            card_number=getattr(gateway, "card_number", ""),
            card_holder_fa=getattr(gateway, "card_holder_fa", ""),
            bank_fa=getattr(gateway, "bank_name_fa", ""),
            review_sla_fa=_REVIEW_SLA_FA,
            payment=_to_pending(result),
        )

    # -- proof -------------------------------------------------------------

    async def attach_receipt(
        self, user_id: uuid.UUID, *, payment_id: uuid.UUID, file_id: str
    ) -> PendingPayment:
        """Fingerprint the receipt from its **bytes**, never from the file id.

        Forwarding a photo produces a fresh Telegram file id for identical
        bytes. Digesting the id would therefore make a re-submitted receipt look
        new and quietly defeat `uq_receipt_digest`, which docs/security.md names
        as the primary defence against the same receipt being approved twice.
        """
        owner_id = await self._require_telegram_id(user_id)
        if self._fetch_receipt is None:
            raise RuntimeError(
                "No receipt fetcher is configured, so the image cannot be "
                "fingerprinted. Refusing rather than digesting the file id."
            )
        image = await self._fetch_receipt(file_id)
        proof = PaymentProof.for_card(
            file_id=file_id,
            image_digest=hashlib.sha256(image).hexdigest(),
            submitted_at=self._clock.now(),
        )
        return await self._submit_proof(proof, payment_id, owner_id)

    async def attach_txid(
        self, user_id: uuid.UUID, *, payment_id: uuid.UUID, txid: str
    ) -> PendingPayment:
        proof = PaymentProof.for_crypto(
            txid=txid,
            network=self._crypto_network,
            submitted_at=self._clock.now(),
        )
        return await self._submit_proof(proof, payment_id, await self._require_telegram_id(user_id))

    # -- internals ---------------------------------------------------------

    async def _begin(
        self,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        coupon_code: str | None,
        *,
        gateway_key: str,
    ) -> tuple[CheckoutResult, Order]:
        telegram_id = await self._require_telegram_id(user_id)
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise LookupError(f"No plan {plan_id}.")
        # Read from order history rather than defaulted. Left False, a
        # first-purchase-only coupon is redeemable forever and every
        # returning customer is priced as a new one.
        is_first = not await self._order_repository.has_completed_order(telegram_id)
        quote = await self._quoting.quote(
            plan_id=plan_id,
            user_id=user_id,
            coupon_code=coupon_code,
            is_first_purchase=is_first,
        )

        # The plan's terms are copied onto the order, not referenced, so a price
        # change next month cannot rewrite what was sold today.
        order = await self._orders.place(
            user_id=telegram_id,
            jalali_year=self._jalali_year,
            plan_id=str(plan_id),
            plan_name_fa=plan.name_fa,
            duration_days=plan.duration_days,
            list_price=quote.base_price,
            total=quote.total,
            product_id=str(quote.product_id),
            traffic_mib=None if plan.quota_gib is None else plan.quota_gib * MIB_PER_GIB,
            device_limit=plan.device_limit,
            discount=quote.base_price - quote.total,
            coupon_code=coupon_code,
        )

        # Committed before a single Rial moves.
        #
        # The order lives on this async session; the wallet debit, the invoice
        # and `OrderPaymentBridge` all live on the synchronous one. A separate
        # transaction cannot see an uncommitted row, so the bridge looked for
        # this order, found nothing, and left it PENDING - and `provision` then
        # refused, because PENDING to PROVISIONING is not a legal transition.
        # The customer's balance had already gone down by then, and the
        # exception rolled this session back, so the order they had paid for
        # ceased to exist.
        await self._session.commit()

        await self._record_coupon_use(quote, user_id=user_id, order_id=order.id)

        year = self._jalali_year
        lines = _lines_for(plan.name_fa, quote)

        def work(scope: SyncScope) -> CheckoutResult:
            return scope.checkout.begin(
                CheckoutRequest(
                    user_id=telegram_id,
                    subject_fa=plan.name_fa,
                    lines=lines,
                    gateway_key=gateway_key,
                    jalali_year=year,
                    metadata={"order_id": order.id, "order_number": order.number},
                )
            )

        result = await self._bridge.run(work)

        # The link OrderPaymentBridge follows on approval. Without it an
        # approved payment cannot find its order and nothing gets provisioned.
        order.invoice_id = result.invoice.id
        await self._order_repository.update(order)
        # Again, for the same reason: whatever happens next - a panel that will
        # not answer, a node with no capacity - the order and its invoice link
        # are already durable, and the admin panel can retry the delivery
        # rather than an operator reconstructing it from a bank statement.
        await self._session.commit()
        return result, order

    async def _submit_proof(
        self, proof: PaymentProof, payment_id: uuid.UUID, owner_id: int
    ) -> PendingPayment:
        def work(scope: SyncScope) -> PendingPayment:
            # The owner is passed so a customer cannot attach proof to
            # somebody else's payment; ids travel through Telegram messages.
            payment = scope.checkout.submit_proof(
                payment_id=_as_stored_id(payment_id), proof=proof, user_id=owner_id
            )
            return PendingPayment(
                payment_id=_as_uuid(payment.id),
                reference=payment.id,
                amount=payment.amount.amount,
                method=_CARD_METHOD.get(payment.method, CardMethod.CARD),
                state=_CARD_STATE.get(payment.state, CardPaymentState.PENDING_REVIEW),
                created_at=payment.created_at,
            )

        return await self._bridge.run(work)

    async def _record_coupon_use(
        self, quote: PriceQuote, *, user_id: uuid.UUID, order_id: str
    ) -> None:
        """Count the redemption against the coupon.

        `Coupon.redeem` and `record_redemption` both existed and neither had a
        caller, so max_redemptions and max_per_user were decorative: a code
        capped at one use worked for everyone, forever.

        Same transaction as the order. A redemption recorded outside it would
        either be lost when the order rolls back, or survive an order that
        never existed.
        """
        if quote.coupon_code is None:
            return
        coupon = await self._coupons.get_by_code(quote.coupon_code)
        if coupon is None:
            return

        discount = quote.base_price - quote.total
        coupon.redeem(user_id=user_id, discount=discount)
        await self._coupons.update(coupon)
        await self._coupons.record_redemption(
            coupon_id=coupon.id,
            user_id=user_id,
            order_id=None,
            discount=discount.amount,
            redeemed_at=self._clock.now(),
        )

    async def _require_telegram_id(self, user_id: uuid.UUID) -> int:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            raise LookupError(f"No user {user_id}.")
        return telegram_id


#: Shown next to every manual payment so the customer knows what "in review"
#: costs them in waiting.
_REVIEW_SLA_FA = "بررسی معمولاً کمتر از ۳۰ دقیقه طول می‌کشد."


def _lines_for(plan_name_fa: str, quote: PriceQuote) -> list[InvoiceLine]:
    """One line for the plan, one for the deduction.

    The invoice records what was charged *and* what was given, because a
    customer disputing a price needs to see the discount that was applied.
    """
    lines = [InvoiceLine(title_fa=plan_name_fa, amount=quote.base_price.amount)]
    discount = quote.base_price.amount - quote.total.amount
    if discount > 0:
        lines.append(InvoiceLine(title_fa="تخفیف", amount=-discount))
    return lines


def _to_pending(result: CheckoutResult) -> PendingPayment:
    payment = result.payment
    return PendingPayment(
        payment_id=_as_uuid(payment.id),
        reference=result.invoice.number,
        amount=payment.amount.amount,
        method=_CARD_METHOD.get(payment.method, CardMethod.CARD),
        state=_CARD_STATE.get(payment.state, CardPaymentState.AWAITING_PROOF),
        created_at=payment.created_at,
    )


def _as_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(int=0)


def _as_stored_id(value: uuid.UUID) -> str:
    """The inverse of `_as_uuid`, and it must be exact.

    Payment ids are `uuid4().hex` - thirty-two characters, no dashes - because
    that is what `Uuid4IdGenerator` produces. `str(UUID)` puts the dashes back,
    so a payment created as "e89789f92d04..." was looked up as
    "e89789f9-2d04-...", matched nothing, and every receipt a customer sent was
    refused with the generic apology. The bot layer speaks UUIDs and the
    payment store speaks strings; this is the one place that has to know they
    are written differently.
    """
    return value.hex


__all__ = ["BotCheckoutAdapter"]
