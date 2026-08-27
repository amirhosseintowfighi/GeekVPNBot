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

import secrets
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from geekvpn.application.notifications.broadcast_service import BroadcastService
from geekvpn.application.notifications.channels import InboxChannel, TelegramChannel
from geekvpn.application.notifications.engine import NotificationEngine
from geekvpn.application.notifications.inbox_service import InboxService
from geekvpn.application.notifications.operator_alerts import (
    APPROVE_LABEL_FA,
    RECEIPT_ALERT_FA,
    RECEIPT_ALERT_NO_IMAGE_FA,
    REJECT_LABEL_FA,
    DeliveryNotifications,
    ReceiptAlerts,
)
from geekvpn.application.notifications.ports import Channel, EventPublisher
from geekvpn.application.notifications.reminders import ReminderService
from geekvpn.application.notifications.subscribers import (
    EngineSupportNotifier,
    PurchaseNotifications,
    WalletNotifications,
    register,
)
from geekvpn.application.payments.adapters import (
    CardTransferGateway,
    CryptoTransferGateway,
    WalletGateway,
)
from geekvpn.application.payments.checkout_service import CheckoutService
from geekvpn.application.payments.refund_service import RefundService
from geekvpn.application.payments.review_service import PaymentReviewService
from geekvpn.application.payments.verification_service import VerificationService
from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.order_service import INVOICE_ORDER_KEY, OrderPaymentBridge
from geekvpn.application.support.search_service import SearchService
from geekvpn.application.support.template_service import TemplateService
from geekvpn.application.support.ticket_service import TicketService
from geekvpn.domain.audit.entry import AuditAction, AuditOutcome
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.payments.events import PaymentApproved, ProofSubmitted
from geekvpn.domain.payments.gateway import GatewayRegistry
from geekvpn.domain.provisioning.events import SubscriptionActivated
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.events.dispatcher import DispatchingEventPublisher
from geekvpn.infrastructure.logging.context import get_correlation_id
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.notifications.audiences import SqlAudienceResolver
from geekvpn.infrastructure.notifications.telegram import (
    HttpOperatorSender,
    HttpTelegramSender,
    TelegramIdIsTheUserId,
)
from geekvpn.infrastructure.payments.iranian_gateways import build as build_online_gateway
from geekvpn.infrastructure.persistence.models.audit import AuditLogModel
from geekvpn.infrastructure.persistence.models.payments import (
    CardAccountModel,
    CryptoAccountModel,
    GatewayAccountModel,
)
from geekvpn.infrastructure.persistence.models.resellers import ResellerModel
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    SyncOrderRepository,
)
from geekvpn.infrastructure.persistence.repositories.subscription_reader import (
    SqlSubscriptionReader,
)
from geekvpn.infrastructure.persistence.repositories.sync_directory import (
    SyncUserDirectory,
)
from geekvpn.infrastructure.persistence.repositories.sync_notifications import (
    SyncBroadcastRepository,
    SyncNotificationRepository,
    SyncPreferencesStore,
)
from geekvpn.infrastructure.persistence.repositories.sync_operators import (
    SyncOperatorDirectory,
)
from geekvpn.infrastructure.persistence.repositories.sync_payments import (
    SyncInvoiceRepository,
    SyncPaymentRepository,
    SyncReceiptDigestRepository,
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


def build_gateway_registry(
    session: Session, *, reseller_id: uuid.UUID | None = None
) -> GatewayRegistry:
    """Register the payment methods this deployment can actually take money by.

    The destination card is read from the database rather than from settings:
    cards rotate constantly in the Iranian market, and a rotation must be
    something support can do in the panel, not a deployment.

    One card is registered under the key ``"card"``, chosen at random from
    those active. Gateway keys are persisted on payment rows forever, so they
    cannot vary per card without making old rows unreadable - but which card
    sits behind the key can, and spreading transfers across several accounts is
    the point of having more than one.

    Random rather than round-robin: this is built per request, in a process
    that may be one of several, so there is nowhere to keep a turn counter that
    all of them would agree on. Random needs no shared state and spreads just
    as well over a day's transfers.

    `sort_order` still decides when only one card should be used - an operator
    who wants that deactivates the others, which is the same control they
    already have.
    """
    registry = GatewayRegistry()
    registry.register(WalletGateway())

    stmt = (
        select(CardAccountModel)
        .where(
            CardAccountModel.active.is_(True),
            # A shop's own cards, and only those. Falling back to the
            # platform's for a reseller who has entered none would send their
            # customer's money to us for a package the reseller has already
            # paid for - charging twice for one service, and silently.
            CardAccountModel.reseller_id.is_(None)
            if reseller_id is None
            else CardAccountModel.reseller_id == reseller_id,
        )
        .order_by(CardAccountModel.sort_order, CardAccountModel.id)
    )
    cards = list(session.execute(stmt).scalars().all())
    card = secrets.choice(cards) if cards else None
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

    # Crypto, from this shop's own addresses.
    #
    # `CryptoTransferGateway` has existed since the payment layer was written
    # and nothing ever constructed it, so the bot offered "pay with crypto" and
    # answered everyone who tapped it with a generic apology. There was nowhere
    # to read an address from.
    crypto_stmt = (
        select(CryptoAccountModel)
        .where(
            CryptoAccountModel.active.is_(True),
            CryptoAccountModel.reseller_id.is_(None)
            if reseller_id is None
            else CryptoAccountModel.reseller_id == reseller_id,
        )
        .order_by(CryptoAccountModel.sort_order, CryptoAccountModel.id)
    )
    wallets = list(session.execute(crypto_stmt).scalars().all())
    if wallets:
        # Random among the active ones, for the same reason cards are: spread
        # the traffic, with no shared turn counter to keep.
        chosen = secrets.choice(wallets)
        registry.register(
            CryptoTransferGateway(address=chosen.address, network=chosen.network)
        )

    # Online gateways, one per configured provider.
    #
    # Registered under the provider's own key rather than a generic "gateway",
    # because the key is stored on every payment row forever: a shop that
    # switches from Zibal to ZarinPal must not make its own history unreadable.
    gateway_stmt = (
        select(GatewayAccountModel)
        .where(
            GatewayAccountModel.active.is_(True),
            GatewayAccountModel.reseller_id.is_(None)
            if reseller_id is None
            else GatewayAccountModel.reseller_id == reseller_id,
        )
        .order_by(GatewayAccountModel.sort_order, GatewayAccountModel.id)
    )
    for account in session.execute(gateway_stmt).scalars().all():
        try:
            registry.register(
                build_online_gateway(account.provider, account.merchant_id_encrypted)
            )
        except KeyError:
            # A provider this build cannot construct - a row from a newer
            # version, or one renamed. Skipped rather than raised: the other
            # payment methods must keep working.
            logger.warning("payments.unknown_gateway", provider=account.provider)
    return registry


class _DeferredEventPublisher:
    """An `EventPublisher` that resolves the real one on first publish.

    `engine` needs a publisher, `events` needs the notification handlers, and
    those handlers need `engine`. Constructing any one of them entered the
    cycle and died with `RecursionError` - a 500 on every request that touched
    the notification stack, which is approving a payment, refunding one,
    crediting a wallet and sending a broadcast.

    Deferring the lookup breaks it without weakening anything: by the time
    something is actually published, `events` has finished building and is
    cached, so the engine publishes into the same dispatch table as everyone
    else. Handing the engine a `LoggingEventPublisher` instead - the trick
    `order_bridge` uses for its own re-entrancy problem - would have broken the
    cycle too, and silently dropped every event the engine emits.
    """

    def __init__(self, resolve: Callable[[], EventPublisher]) -> None:
        self._resolve = resolve

    def publish_all(self, events: Sequence[object]) -> None:
        self._resolve().publish_all(events)


# Deliberately not `slots=True`: `cached_property` needs a real `__dict__`.
@dataclass
class SyncScope:
    """Everything bound to a single synchronous database session."""

    container: Container
    session: Session
    #: Which shop this unit of work belongs to. Set when it was started from a
    #: reseller's bot, `None` for the platform's own and for every background
    #: job - a sweeper reconciling every payment belongs to no single shop.
    reseller_id: uuid.UUID | None = None

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
        # The service exists now, and the customer is owed the link. Written
        # long ago as `on_service_provisioned` and subscribed by nothing, so a
        # paying customer watched a chat go quiet.
        table[SubscriptionActivated.name] = self.delivery_notifications.on_subscription_activated
        # And an operator is owed the receipt. The panel had it in a queue
        # nobody has open at one in the morning.
        table[ProofSubmitted.name] = self.receipt_alerts.on_proof_submitted
        for name, handler in table.items():
            publisher.subscribe(name, handler)
        return publisher

    @cached_property
    def operator_directory(self) -> SyncOperatorDirectory:
        return SyncOperatorDirectory(self.session)

    @cached_property
    def delivery_notifications(self) -> DeliveryNotifications:
        return DeliveryNotifications(engine=self.engine)

    @cached_property
    def receipt_alerts(self) -> ReceiptAlerts:
        """Sends the receipt itself, with the two buttons that decide it.

        Not through the notification engine: that renders a customer template
        as text, and this is an image with actions attached. Without a bot
        token it still constructs - the sender simply has nowhere to post, and
        the alert fails into a log line rather than taking down the transaction
        that accepted the customer's receipt.
        """
        return ReceiptAlerts(
            sender=HttpOperatorSender(
                self.container.settings.telegram.bot_token.get_secret_value()
            ),
            directory=self.operator_directory,
            payments=self.payments,
            approve_label=APPROVE_LABEL_FA,
            reject_label=REJECT_LABEL_FA,
            caption=RECEIPT_ALERT_FA,
            no_image_caption=RECEIPT_ALERT_NO_IMAGE_FA,
        )

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
            order_id_for_invoice=self._order_id_for_invoice,
        )

    def _order_id_for_invoice(self, invoice_id: str) -> str | None:
        """The order an invoice was raised for, from its own metadata.

        `INVOICE_ORDER_KEY` has been travelling on every checkout since the bot
        was written and nothing ever read it. It is the only way to connect a
        wallet payment to its order, because that payment settles inside the
        call that creates the invoice - before anything can write the invoice
        id back onto the order.
        """
        invoice = self.invoices.get(invoice_id)
        if invoice is None:
            return None
        order_id = invoice.metadata.get(INVOICE_ORDER_KEY)
        return str(order_id) if order_id else None

    @cached_property
    def orders(self) -> SyncOrderRepository:
        return SyncOrderRepository(self.session)

    @cached_property
    def directory(self) -> SyncUserDirectory:
        """Telegram ids to people, for queues that only store the id."""
        return SyncUserDirectory(self.session)

    @cached_property
    def audit(self) -> SyncAuditLog:
        return SyncAuditLog(session=self.session, clock=self.container.clock)

    @cached_property
    def gateways(self) -> GatewayRegistry:
        """The payment methods *this shop* can take money by.

        A reseller's customer transfers to the reseller's card. The reseller
        has already bought the package out of their credit, so money arriving
        on ours for it would charge twice for one service.
        """
        return build_gateway_registry(self.session, reseller_id=self.reseller_id)

    # -- repositories ------------------------------------------------------

    @cached_property
    def invoices(self) -> SyncInvoiceRepository:
        return SyncInvoiceRepository(self.session, reseller_id=self.reseller_id)

    @cached_property
    def payments(self) -> SyncPaymentRepository:
        return SyncPaymentRepository(self.session, reseller_id=self.reseller_id)

    @cached_property
    def wallets(self) -> SyncWalletRepository:
        return SyncWalletRepository(self.session, reseller_id=self.reseller_id)

    @cached_property
    def tickets(self) -> SyncTicketRepository:
        return SyncTicketRepository(self.session, reseller_id=self.reseller_id)

    @cached_property
    def reply_templates(self) -> SyncTemplateRepository:
        return SyncTemplateRepository(self.session)

    @cached_property
    def notifications(self) -> SyncNotificationRepository:
        return SyncNotificationRepository(self.session, reseller_id=self.reseller_id)

    @cached_property
    def preferences(self) -> SyncPreferencesStore:
        return SyncPreferencesStore(self.session)

    @cached_property
    def broadcasts(self) -> SyncBroadcastRepository:
        return SyncBroadcastRepository(self.session, reseller_id=self.reseller_id)

    # -- notifications -----------------------------------------------------

    def _bot_token(self) -> str:
        """Which bot speaks for this shop.

        A reseller's customer has never started *our* bot, and Telegram refuses
        a message from a bot the recipient has not spoken to first. So every
        delivery link, expiry warning and payment approval sent to them from
        our token was refused - a silent failure, because a refusal here is
        recorded as a suppression and looks like a customer who blocked us.

        No fallback to ours. Sending from the wrong bot does not merely fail,
        it fails in a way that reads as the customer's fault.
        """
        if self.reseller_id is None:
            return self.container.settings.telegram.bot_token.get_secret_value()

        row = self.session.get(ResellerModel, self.reseller_id)
        token = (row.bot_token_encrypted or "") if row is not None else ""
        if not token:
            logger.warning(
                "notify.reseller_has_no_bot",
                reseller=str(self.reseller_id),
                detail="their customers reach the Mini App inbox only",
            )
        return token

    @cached_property
    def channels(self) -> Sequence[Channel]:
        """The inbox, and Telegram when a bot token is configured.

        This used to be the inbox alone, on the reasoning that a Telegram
        channel needs a sender and a chat-id resolver that belong to the bot
        process. Both turned out to be small - one HTTP call and an identity
        function - and the cost of leaving them out was the whole point of the
        feature: a broadcast reported "sent 2/2" and arrived on nobody's phone,
        because the inbox it reached is only visible inside the Mini App.

        Without a token the inbox is still the honest answer: registering a
        channel that cannot authenticate would report deliveries that never
        happened, which is the failure the original comment was guarding
        against.
        """
        token = self._bot_token()
        if not token:
            logger.warning(
                "notify.telegram.disabled",
                detail="TELEGRAM__BOT_TOKEN is unset; notifications reach the Mini App inbox only",
            )
            return (InboxChannel(),)

        return (
            InboxChannel(),
            TelegramChannel(
                sender=HttpTelegramSender(
                    token,
                    parse_mode=self.container.settings.telegram.parse_mode,
                    # The same pack the bot decorates its screens from, so an
                    # approved payment and the screen it came from do not come
                    # from two different sets of ducks.
                    sticker_set=self.container.settings.telegram.sticker_set,
                ),
                chat_ids=TelegramIdIsTheUserId(),
            ),
        )

    @cached_property
    def engine(self) -> NotificationEngine:
        return NotificationEngine(
            notifications=self.notifications,
            preferences=self.preferences,
            channels=self.channels,
            clock=self.container.clock,
            ids=self.ids,
            # Deferred, not `self.events`: the handlers `events` registers need
            # this engine, so reading it here re-enters its own construction.
            events=_DeferredEventPublisher(lambda: self.events),
        )

    @cached_property
    def audiences(self) -> SqlAudienceResolver:
        return SqlAudienceResolver(self.session)

    @cached_property
    def broadcast_service(self) -> BroadcastService:
        """Composing and sending admin broadcasts.

        The last piece of Phase 10 to be wired: BroadcastService has existed
        since it was written, with nothing implementing its AudienceResolver
        and nothing constructing it, so every broadcast route in the admin
        panel answered 404.
        """
        return BroadcastService(
            engine=self.engine,
            broadcasts=self.broadcasts,
            audiences=self.audiences,
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
    def receipt_digests(self) -> SyncReceiptDigestRepository:
        return SyncReceiptDigestRepository(self.session)

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
            # Without this the digest table is read and never written, so
            # the duplicate-receipt guard can only ever miss.
            digests=self.receipt_digests,
            # Where a gateway sends the customer back. The API's own base URL:
            # the callback is served by this application, not the panel.
            callback_base=self.container.settings.app.base_url,
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


def build_sync_scope(
    container: Container, session: Session, *, reseller_id: uuid.UUID | None = None
) -> SyncScope:
    return SyncScope(container=container, session=session, reseller_id=reseller_id)


__all__ = [
    "LoggingEventPublisher",
    "SyncAuditLog",
    "SyncScope",
    "Uuid4IdGenerator",
    "build_gateway_registry",
    "build_sync_scope",
]
