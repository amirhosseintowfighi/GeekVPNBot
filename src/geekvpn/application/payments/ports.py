"""Collaboration ports for the payment services.

The application depends on these Protocols; ``infrastructure`` implements them
and the tests use in-memory fakes. That is what lets the whole payment system
be tested without Postgres, without Redis and without a bank.

Three conventions, each load-bearing:

**The ports are synchronous.** Payment logic is arithmetic and state checks,
not I/O, and the services here are pure orchestration over aggregates. Making
them async would force every test to spin an event loop for code that never
awaits anything real. The async boundary lives one layer out, in the adapters
that actually talk to Postgres and Telegram.

**Identifier types follow the domain.** A user is an ``int`` because it is a
Telegram id; payments and invoices are ``str`` because their ids travel in
callback data and invoice numbers.

**Repositories expose ``save``, never ``add`` plus ``update``.** The services
do not track whether an aggregate is new, and requiring them to would create
exactly one class of bug: the correct object written with the wrong verb.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.payments.enums import PaymentState
from geekvpn.domain.payments.invoice import Invoice
from geekvpn.domain.payments.payment import Payment
from geekvpn.domain.payments.wallet import Wallet


@runtime_checkable
class Clock(Protocol):
    """Time as a dependency. Always timezone-aware UTC."""

    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    """Source of new identifiers.

    Injected rather than called as ``uuid4()`` inside the services so a test
    can assert on an exact id instead of matching a regex.
    """

    def new_id(self) -> str: ...


@runtime_checkable
class EventPublisher(Protocol):
    """Where domain events go once a use case has committed.

    ``publish_all`` takes a batch because a single checkout emits an invoice
    event and a payment event that must not be observable separately.
    """

    def publish_all(self, events: Iterable[object]) -> None: ...


@runtime_checkable
class PaymentAuditLog(Protocol):
    """The record of who touched money and why.

    Separate from domain events on purpose. Events describe what happened to
    the business; the audit log answers "which operator did this, and what did
    they see at the time". Only the second one is any use in a dispute.
    """

    def record(
        self,
        *,
        action: str,
        actor_id: int | None,
        payment_id: str,
        details: dict[str, object] | None = None,
    ) -> None: ...


@runtime_checkable
class ReceiptDigestRepository(Protocol):
    """Writes the duplicate-receipt guard.

    Separate from `PaymentRepository` because the read side already lives
    there; this is only the claim, and it is the half that was missing.
    """

    def claim(
        self,
        digest: str,
        *,
        payment_id: str,
        user_id: int,
        reference: str,
        method: str,
        seen_at: datetime,
    ) -> None:
        """Record the digest.

        :raises DuplicateReceipt: the digest has already been claimed. The
            implementation translates its own constraint violation, so this
            layer never sees a driver exception.
        """
        ...


@runtime_checkable
class WalletRepository(Protocol):
    def get_or_create(self, user_id: int) -> Wallet:
        """Load a wallet, inventing an empty one for a user who never paid.

        Never returns ``None``: "no wallet" and "a wallet with no entries" are
        the same thing to a customer, and making every caller handle a null
        only produces inconsistent handling of a case that cannot matter.
        """
        ...

    def save(self, wallet: Wallet) -> None:
        """Persist the entries appended since the wallet was loaded.

        Implementations append; they never rewrite history. A ledger whose
        rows can be updated is not a ledger.
        """
        ...

    def lock(self, user_id: int) -> None:
        """Serialise concurrent writes for one user.

        Called before a debit. Postgres implements it with ``SELECT ... FOR
        UPDATE``; the in-memory fake does nothing because it has no
        concurrency. Without it, two purchases in the same second can both see
        a sufficient balance and both succeed - the aggregate can only refuse
        based on the ledger it was handed.
        """
        ...


@runtime_checkable
class InvoiceRepository(Protocol):
    def get(self, invoice_id: str) -> Invoice | None: ...

    def get_by_number(self, number: str) -> Invoice | None:
        """Look up by the number a customer quotes to support."""
        ...

    def save(self, invoice: Invoice) -> None: ...

    def list_for_user(self, user_id: int, *, limit: int, offset: int = 0) -> Sequence[Invoice]: ...

    def count_for_user(self, user_id: int) -> int: ...

    def next_sequence(self, *, year: int) -> int:
        """Reserve the next invoice number within a Jalali year.

        Must be atomic, and must not hand back a number even if the caller's
        transaction later rolls back. A gap in the sequence is invisible; a
        duplicate invoice number is a bookkeeping incident.
        """
        ...


@runtime_checkable
class PaymentRepository(Protocol):
    def get(self, payment_id: str) -> Payment | None: ...

    def save(self, payment: Payment) -> None: ...

    def find_by_digest(self, digest: str) -> Payment | None:
        """Find any earlier payment that used the same evidence.

        This is the query that stops one genuine receipt being forwarded
        against three orders. Because ``PaymentProof`` digests a photo's bytes
        and a txid the same way, one lookup covers both methods.
        """
        ...

    def find_by_gateway_reference(self, *, gateway_key: str, reference: str) -> Payment | None:
        """Resolve a provider callback back to our payment.

        Also the idempotency key for webhooks: a provider that delivers the
        same notification three times must settle the payment once.
        """
        ...

    def list_for_user(self, user_id: int, *, limit: int, offset: int = 0) -> Sequence[Payment]: ...

    def in_state(
        self, state: PaymentState, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Payment]:
        """Everything sitting in one state - the review queue, mostly."""
        ...

    def count_in_state(self, state: PaymentState) -> int: ...

    def expiring_before(self, now: datetime, *, limit: int = 100) -> Sequence[Payment]:
        """Open payments whose window has closed, for the sweeper.

        Returns candidates, not verdicts: the sweeper re-checks each one's
        state before expiring it, because a payment can be approved between
        the query and the write.
        """
        ...


@runtime_checkable
class ProvisioningService(Protocol):
    """What happens after money is recognised.

    Behind a port so the payment services never import the panel layer. A
    payment service that knows how to create an X-UI client is a payment
    service that cannot be tested, and a panel change that breaks checkout.
    """

    def provision(self, *, user_id: int, plan_id: str, payment_id: str) -> str:
        """Create or extend the subscription. Returns its id."""
        ...


@runtime_checkable
class PaymentNotifier(Protocol):
    """Customer-facing messages about money.

    Implementations swallow and log their own failures: a Telegram outage must
    never roll back a payment that already succeeded.
    """

    def payment_approved(
        self, user_id: int, *, amount: int, invoice_number: str | None = None
    ) -> None: ...

    def payment_rejected(self, user_id: int, *, amount: int, reason_fa: str) -> None: ...

    def wallet_credited(
        self, user_id: int, *, amount: int, balance: int, reason_fa: str
    ) -> None: ...

    def refund_issued(self, user_id: int, *, amount: int, reason_fa: str) -> None: ...


__all__ = [
    "Clock",
    "EventPublisher",
    "IdGenerator",
    "InvoiceRepository",
    "PaymentAuditLog",
    "PaymentNotifier",
    "PaymentRepository",
    "ProvisioningService",
    "WalletRepository",
]
