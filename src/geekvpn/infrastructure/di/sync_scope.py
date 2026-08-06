"""Synchronous request scope: billing, support and notifications.

``scope.py`` wires the asynchronous half of the system. This module wires the
synchronous half, for one reason: every service in ``application/payments``,
``application/support`` and ``application/notifications`` is synchronous. They
were written and tested that way, and turning them into coroutines to satisfy
the transport would have thrown away several hundred passing tests to buy
nothing a worker thread does not already buy.

So the API keeps its async transport, hands each unit of work to a thread (see
the admin routers), and that thread gets one of these scopes: one synchronous
session, one set of repositories, one set of services.

Everything is a ``cached_property``, so an endpoint that only reads the review
queue does not pay for constructing a notification engine.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from geekvpn.application.notifications.channels import InboxChannel
from geekvpn.application.notifications.engine import NotificationEngine
from geekvpn.application.notifications.inbox_service import InboxService
from geekvpn.application.notifications.reminders import ReminderService
from geekvpn.application.notifications.subscribers import (
    EngineSupportNotifier,
    PurchaseNotifications,
    WalletNotifications,
    register,
)
from geekvpn.application.payments.adapters import (
    CardTransferGateway,
    WalletGateway,
)
from geekvpn.application.payments.checkout_service import CheckoutService
from geekvpn.application.payments.refund_service import RefundService
from geekvpn.application.payments.review_service import PaymentReviewService
from geekvpn.application.payments.verification_service import VerificationService
from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.order_service import OrderPaymentBridge
from geekvpn.application.support.search_service import SearchService
from geekvpn.application.support.template_service import TemplateService
from geekvpn.application.support.ticket_service import TicketService
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.payments.events import PaymentApproved
from geekvpn.domain.payments.gateway import GatewayRegistry
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.events.dispatcher import DispatchingEventPublisher
from geekvpn.infrastructure.logging.context import get_correlation_id
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.persistence.models.audit import AuditLogModel
from geekvpn.infrastructure.persistence.models.payments import CardAccountModel
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SyncOrderRepository,
)
from geekvpn.infrastructure.persistence.repositories.subscription_reader import (
    SqlSubscriptionReader,
)
from geekvpn.infrastructure.persistence.repositories.sync_notifications import (
    SyncBroadcastRepository,
    SyncNotificationRepository,
    SyncPreferencesStore,
)
from geekvpn.infrastructure.persistence.repositories.sync_payments import (
    SyncInvoiceRepository,
    SyncPaymentRepository,
    SyncWalletRepository,
)
from geekvpn.infrastructure.persistence.repositories.sync_support import (
    SyncTemplateRepository,
    SyncTicketRepository,
)

logger = get_logger(__name__)


class Uuid4IdGenerator:
    """Concrete ``IdGenerator``.

    Random ids rather than a database sequence: an id is needed *before* the
    row exists (a payment id goes into the transfer description the customer
    reads), and a random id also stops anyone from counting our order volume
    by watching their own invoice numbers climb.
    """

    def new_id(self) -> str:
        return uuid.uuid4().hex


class LoggingEventPublisher:
    """Concrete ``EventPublisher``: writes every domain event to the log.

    This is deliberately not a message bus. The aggregates already record their
    events and the services already collect them; what was missing was somewhere
    to put them. A structured log line is enough to answer "what happened to
    this payment?" today, and the day a bus arrives this class is the only
    place that changes.

    It never raises. An event is a description of something that *already*
    happened; failing the operation because we could not describe it would turn
    a successful refund into an error the customer sees.
    """

    def publish_all(self, events: Iterable[object]) -> None:
        for event in events:
            try:
                name = getattr(type(event), "name", type(event).__name__)
                payload = event.payload() if hasattr(event, "payload") else {}
                logger.info("domain.event", event_type=name, payload=payload)
            except Exception:  # pragma: no cover - never break the caller
                logger.warning("domain.event_unloggable", event_type=type(event).__name__)


@dataclass(slots=True)
class SyncAuditLog:
    """Concrete ``PaymentAuditLog``, writing the real audit table.

    Two mismatches had to be bridged here rather than papered over:

    1. ``AuditLogRecorder`` is a coroutine and takes an ``AuditAction`` member.
       These services are synchronous and pass a plain string, so this adapter
       resolves the string against the enum when it can and stores it verbatim
       when it cannot. ``audit_logs.action`` is a ``String(64)`` with no CHECK,
       so a new payment action never needs a migration to be auditable.
    2. ``actor_id`` in the payment services is a Telegram/admin integer, while
       ``audit_logs.actor_id`` is a UUID column. The integer is therefore
       recorded as ``actor_label`` and inside the metadata, and the UUID column
       is left null. Coercing an integer into a UUID column would either crash
       or, worse, fabricate an identity.
    """

    session: Session
    clock: Clock

    def record(
        self,
        *,
        action: str,
        actor_id: int | None,
        payment_id: str,
        details: dict[str, object] | None = None,
    ) -> None:
        try:
            resolved: str = AuditAction(action).value
        except ValueError:
            resolved = action

        metadata: dict[str, Any] = dict(details or {})
        if actor_id is not None:
            metadata["actor_numeric_id"] = actor_id

        self.session.add(
            AuditLogModel(
                id=uuid.uuid4(),
                action=resolved[:64],
                outcome=AuditOutcome.SUCCESS.value,
                occurred_at=self.clock.now(),
                actor_type=(
                    SubjectType.ADMIN.value if actor_id is not None else SubjectType.SYSTEM.value
                ),
                actor_id=None,
                actor_label=str(actor_id) if actor_id is not None else None,
                target_type="payment",
                target_id=payment_id,
                correlation_id=get_correlation_id(),
                audit_metadata=metadata,
            )
        )
        # No flush: the audit row rides the caller's transaction on purpose. An
        # audit line for a refund that then rolls back would be a lie.
        logger.info("audit.payment", action=resolved, payment_id=payment_id)


def build_gateway_registry(session: Session) -> GatewayRegistry:
    """Register the payment methods this deployment can actually take money by.

    The destination card is read from the database rather than from settings:
    cards rotate constantly in the Iranian market, and a rotation must be
    something support can do in the panel, not a deployment.

    Only the highest-priority active card is registered under the key
    ``"card"``. Gateway keys are persisted on payment rows forever, so they
    cannot vary per card without making old rows unreadable.
    """
    registry = GatewayRegistry()
    registry.register(WalletGateway())

    stmt = (
        select(CardAccountModel)
        .where(CardAccountModel.active.is_(True))
        .order_by(CardAccountModel.sort_order, CardAccountModel.id)
        .limit(1)
    )
    card = session.execute(stmt).scalars().first()
    if card is not None:
        registry.register(
            CardTransferGateway(
                card_number=card.card_number,
                card_holder_fa=card.holder_fa,
                bank_name_fa=card.bank_fa,
            )
        )
    else:
        # Not an error: a fresh install has no card yet. The bot simply will
        # not offer card-to-card, which is better than offering a button that
        # sends money nowhere.
        logger.warning("payments.no_active_card", detail="card-to-card is unavailable")
    return registry


# Deliberately not `slots=True`: `cached_property` needs a real `__dict__`.
@dataclass
class SyncScope:
    """Everything bound to a single synchronous database session."""

    container: Container
    session: Session

    # -- shared adapters ---------------------------------------------------

    @cached_property
    def ids(self) -> Uuid4IdGenerator:
        return Uuid4IdGenerator()

    @cached_property
    def events(self) -> DispatchingEventPublisher:
        """The real publisher: logs *and* delivers.

        Built lazily and cached, so every service in this scope shares one
        dispatch table. Constructing a second one per service would mean an
        event published by the review service reached the notification handlers
        but not the provisioning bridge, which is exactly the class of bug that
        made both of them inert before.
        """
        publisher = DispatchingEventPublisher()
        table: dict[str, Any] = {}
        register(
            table,
            wallet=self.wallet_notifications,
            purchases=self.purchase_notifications,
        )
        table[PaymentApproved.name] = self.order_bridge.on_payment_approved
        for name, handler in table.items():
            publisher.subscribe(name, handler)
        return publisher

    @cached_property
    def order_bridge(self) -> OrderPaymentBridge:
        """Moves an order to PAID when its payment is approved.

        Uses ``LoggingEventPublisher`` for its own output rather than
        ``self.events``: the bridge is *called by* ``self.events``, and handing
        it the same publisher would let an ``OrderPaid`` handler re-enter
        dispatch while the first delivery is still unwinding.
        """
        return OrderPaymentBridge(
            orders=self.orders,
            clock=self.container.clock,
            events=LoggingEventPublisher(),
        )

    @cached_property
    def orders(self) -> SyncOrderRepository:
        return SyncOrderRepository(self.session)

    @cached_property
    def audit(self) -> SyncAuditLog:
        return SyncAuditLog(session=self.session, clock=self.container.clock)

    @cached_property
    def gateways(self) -> GatewayRegistry:
        return build_gateway_registry(self.session)

    # -- repositories ------------------------------------------------------

    @cached_property
    def invoices(self) -> SyncInvoiceRepository:
        return SyncInvoiceRepository(self.session)

    @cached_property
    def payments(self) -> SyncPaymentRepository:
        return SyncPaymentRepository(self.session)

    @cached_property
    def wallets(self) -> SyncWalletRepository:
        return SyncWalletRepository(self.session)

    @cached_property
    def tickets(self) -> SyncTicketRepository:
        return SyncTicketRepository(self.session)

    @cached_property
    def reply_templates(self) -> SyncTemplateRepository:
        return SyncTemplateRepository(self.session)

    @cached_property
    def notifications(self) -> SyncNotificationRepository:
        return SyncNotificationRepository(self.session)

    @cached_property
    def preferences(self) -> SyncPreferencesStore:
        return SyncPreferencesStore(self.session)

    @cached_property
    def broadcasts(self) -> SyncBroadcastRepository:
        return SyncBroadcastRepository(self.session)

    # -- notifications -----------------------------------------------------

    @cached_property
    def channels(self) -> Sequence[InboxChannel]:
        """Only the in-app inbox for now.

        The Telegram channel needs a bot sender and a chat-id resolver, which
        belong to the bot process; the API registering a half-built Telegram
        channel would report deliveries that never happened.
        """
        return (InboxChannel(),)

    @cached_property
    def engine(self) -> NotificationEngine:
        return NotificationEngine(
            notifications=self.notifications,
            preferences=self.preferences,
            channels=self.channels,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
        )

    @cached_property
    def subscription_reader(self) -> SqlSubscriptionReader:
        return SqlSubscriptionReader(self.session)

    @cached_property
    def reminders(self) -> ReminderService:
        """The expiry and traffic sweeps. Run by the worker, not by a request."""
        return ReminderService(
            engine=self.engine,
            subscriptions=self.subscription_reader,
            clock=self.container.clock,
            events=self.events,
        )

    @cached_property
    def inbox(self) -> InboxService:
        return InboxService(
            notifications=self.notifications,
            clock=self.container.clock,
            events=self.events,
        )

    @cached_property
    def wallet_notifications(self) -> WalletNotifications:
        return WalletNotifications(engine=self.engine)

    @cached_property
    def purchase_notifications(self) -> PurchaseNotifications:
        return PurchaseNotifications(engine=self.engine)

    # -- billing -----------------------------------------------------------

    @cached_property
    def checkout(self) -> CheckoutService:
        return CheckoutService(
            invoices=self.invoices,
            payments=self.payments,
            wallets=self.wallets,
            gateways=self.gateways,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
            audit=self.audit,
        )

    @cached_property
    def review(self) -> PaymentReviewService:
        return PaymentReviewService(
            payments=self.payments,
            invoices=self.invoices,
            wallets=self.wallets,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
            audit=self.audit,
        )

    @cached_property
    def refunds(self) -> RefundService:
        return RefundService(
            payments=self.payments,
            invoices=self.invoices,
            wallets=self.wallets,
            gateways=self.gateways,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
            audit=self.audit,
        )

    @cached_property
    def verification(self) -> VerificationService:
        return VerificationService(
            payments=self.payments,
            invoices=self.invoices,
            wallets=self.wallets,
            gateways=self.gateways,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
            audit=self.audit,
        )

    @cached_property
    def wallet(self) -> WalletService:
        return WalletService(
            wallets=self.wallets,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
            audit=self.audit,
        )

    # -- support -----------------------------------------------------------

    @cached_property
    def support_notifier(self) -> EngineSupportNotifier:
        return EngineSupportNotifier(engine=self.engine)

    @cached_property
    def support(self) -> TicketService:
        return TicketService(
            tickets=self.tickets,
            templates=self.reply_templates,
            clock=self.container.clock,
            ids=self.ids,
            events=self.events,
            notifier=self.support_notifier,
        )

    @cached_property
    def support_templates(self) -> TemplateService:
        return TemplateService(
            templates=self.reply_templates,
            clock=self.container.clock,
            ids=self.ids,
        )

    @cached_property
    def support_search(self) -> SearchService:
        return SearchService(tickets=self.tickets, clock=self.container.clock)


def build_sync_scope(container: Container, session: Session) -> SyncScope:
    return SyncScope(container=container, session=session)


__all__ = [
    "LoggingEventPublisher",
    "SyncAuditLog",
    "SyncScope",
    "Uuid4IdGenerator",
    "build_gateway_registry",
    "build_sync_scope",
]
