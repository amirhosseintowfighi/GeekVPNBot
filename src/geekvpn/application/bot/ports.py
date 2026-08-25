"""Everything the bot needs from the outside world.

Eight Protocols. If a handler wants something that is not here, that is a
signal to add a port - not to reach into a repository directly.

`CheckoutService` is where the payment methods live. Adding a bank gateway
later means adding `begin_gateway` here and one button in the purchase
keyboard; no flow restructuring, because card and crypto already established
the "create intent, collect proof, wait for admin" shape that a gateway
collapses into a single step.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from geekvpn.application.bot.read_models import (
    CardPaymentDetails,
    CryptoPaymentDetails,
    NotificationPreferences,
    PendingPayment,
    ProfileSummary,
    ReferralSummary,
    ServerStatusRow,
    SubscriptionCard,
    TicketCard,
    WalletSnapshot,
    WalletTransaction,
)


@runtime_checkable
class SubscriptionReader(Protocol):
    async def list_for_user(self, user_id: uuid.UUID) -> list[SubscriptionCard]: ...

    async def rotate_link(
        self, user_id: uuid.UUID, subscription_id: uuid.UUID
    ) -> SubscriptionCard: ...


@runtime_checkable
class WalletReader(Protocol):
    async def snapshot(self, user_id: uuid.UUID) -> WalletSnapshot: ...

    async def transactions(
        self, user_id: uuid.UUID, *, limit: int = 8, offset: int = 0
    ) -> list[WalletTransaction]: ...

    async def transaction_count(self, user_id: uuid.UUID) -> int: ...


@runtime_checkable
class ReferralReader(Protocol):
    async def summary(self, user_id: uuid.UUID) -> ReferralSummary: ...


@runtime_checkable
class ProfileReader(Protocol):
    async def summary(self, user_id: uuid.UUID) -> ProfileSummary: ...

    async def set_display_name(self, user_id: uuid.UUID, display_name: str) -> ProfileSummary: ...


@runtime_checkable
class ServerStatusReader(Protocol):
    async def rows(self) -> list[ServerStatusRow]: ...


@runtime_checkable
class TicketReader(Protocol):
    async def open_ticket(self, user_id: uuid.UUID, *, topic: str, message: str) -> TicketCard: ...

    async def list_for_user(self, user_id: uuid.UUID) -> list[TicketCard]: ...


@runtime_checkable
class PreferencesStore(Protocol):
    async def load(self, user_id: uuid.UUID) -> NotificationPreferences: ...

    async def save(
        self, user_id: uuid.UUID, preferences: NotificationPreferences
    ) -> NotificationPreferences: ...


@runtime_checkable
class CheckoutService(Protocol):
    """Payment intents.

    Card and crypto both end in `PaymentState.PENDING_REVIEW` and wait for an
    admin. There is deliberately no auto-approve path anywhere in this
    interface - approval is an admin-panel action, not something a customer
    can trigger by submitting a convincing-looking receipt.
    """

    async def pay_from_wallet(
        self, user_id: uuid.UUID, *, plan_id: uuid.UUID, coupon_code: str | None = None
    ) -> SubscriptionCard: ...

    async def begin_card(
        self, user_id: uuid.UUID, *, plan_id: uuid.UUID, coupon_code: str | None = None
    ) -> CardPaymentDetails: ...

    async def begin_crypto(
        self, user_id: uuid.UUID, *, plan_id: uuid.UUID, coupon_code: str | None = None
    ) -> CryptoPaymentDetails: ...

    async def begin_topup(
        self, user_id: uuid.UUID, *, amount: int, method: str
    ) -> CardPaymentDetails | CryptoPaymentDetails: ...

    async def awaiting_proof(self, user_id: uuid.UUID) -> list[PendingPayment]:
        """Payments this customer still owes us a receipt for.

        The bot needs it to attach a photo that arrives with no flow
        behind it. Someone who started a card payment in the Mini App
        and then sends the receipt in the chat has no FSM state at all,
        and asking them to start over is asking them to pay twice.
        """
        ...

    async def attach_receipt(
        self, user_id: uuid.UUID, *, payment_id: uuid.UUID, file_id: str
    ) -> PendingPayment: ...

    async def attach_txid(
        self, user_id: uuid.UUID, *, payment_id: uuid.UUID, txid: str
    ) -> PendingPayment: ...
