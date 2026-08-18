"""Synchronous billing repositories, shaped to the application ports.

Why this file exists at all
---------------------------
There are two repository families over the same tables, and that is deliberate
rather than an accident waiting to be deduplicated:

* ``payments.py`` is asynchronous and speaks the language of the write path
  (``add`` / ``update``). It is what the bot and the Mini App will use.
* This module is synchronous and implements ``application/payments/ports.py``
  verbatim (``get`` / ``save`` / ``in_state`` / ...). Every service in
  ``application/payments`` is synchronous: ``CheckoutService.begin`` calls
  ``self._payments.save(payment)`` with no ``await`` anywhere in the call tree.

An async repository cannot be handed to a synchronous service. The alternative
was to rewrite six tested services as coroutines; that would have thrown away
the 131 passing payment tests to save one adapter file. So the services keep
their synchronous contract, run in a worker thread (see the admin routers), and
this module is what they talk to.

House rules, unchanged from the async siblings:

* **Never commit.** The caller owns the transaction.
* **Filter in SQL, not in Python.**
* **Re-read before write.** ``save`` is an upsert: load the row, apply the
  aggregate onto it, and only insert when the row is genuinely new.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.payments.enums import PaymentState
from geekvpn.domain.payments.errors import DuplicateReceipt
from geekvpn.domain.payments.invoice import INVOICE_PREFIX, Invoice
from geekvpn.domain.payments.payment import Payment
from geekvpn.domain.payments.wallet import Wallet
from geekvpn.infrastructure.persistence.mappers.payments import (
    invoice_apply,
    invoice_to_domain,
    invoice_to_row,
    payment_apply,
    payment_to_domain,
    payment_to_row,
    refund_to_row,
    wallet_entry_to_row,
    wallet_to_domain,
)
from geekvpn.infrastructure.persistence.models.payments import (
    InvoiceModel,
    PaymentModel,
    ReceiptDigestModel,
    RefundModel,
    WalletEntryModel,
)

#: Namespace for the wallet advisory lock. Two different subsystems taking
#: ``pg_advisory_xact_lock(user_id)`` on the same integer would deadlock each
#: other for reasons neither could see, so the wallet gets its own high bits.
WALLET_LOCK_NAMESPACE = 947_120_002


class SyncInvoiceRepository:
    """``application.payments.ports.InvoiceRepository``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, invoice_id: str) -> Invoice | None:
        row = self._session.get(InvoiceModel, invoice_id)
        return invoice_to_domain(row) if row is not None else None

    def get_by_number(self, number: str) -> Invoice | None:
        stmt = select(InvoiceModel).where(InvoiceModel.number == number)
        row = self._session.execute(stmt).scalar_one_or_none()
        return invoice_to_domain(row) if row is not None else None

    def save(self, invoice: Invoice) -> None:
        row = self._session.get(InvoiceModel, invoice.id)
        if row is None:
            self._session.add(invoice_to_row(invoice))
        else:
            invoice_apply(row, invoice)
        self._session.flush()

    def list_for_user(self, user_id: int, *, limit: int, offset: int = 0) -> Sequence[Invoice]:
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.user_id == user_id)
            .order_by(InvoiceModel.issued_at.desc(), InvoiceModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [invoice_to_domain(row) for row in self._session.execute(stmt).scalars().all()]

    def count_for_user(self, user_id: int) -> int:
        stmt = select(func.count()).select_from(InvoiceModel).where(InvoiceModel.user_id == user_id)
        return int(self._session.execute(stmt).scalar_one())

    def next_sequence(self, *, year: int) -> int:
        """The next invoice number for this Jalali year, starting at 1.

        One-based because `format_invoice_number` refuses a sequence of zero,
        so returning a bare count meant the first invoice of every Jalali year
        raised instead of being issued.

        The pattern is anchored to the real number format. A bare ``%1405%``
        also matches an id or an amount containing those digits, which would
        silently skip numbers.

        FOR UPDATE on the matching rows makes allocation atomic: two checkouts
        in the same second would otherwise read the same count and claim the
        same number, and `invoices.number` is unique.
        """
        pattern = f"{INVOICE_PREFIX}-{year:04d}-%"
        self._session.execute(
            select(InvoiceModel.id).where(InvoiceModel.number.like(pattern)).with_for_update()
        )
        stmt = (
            select(func.count()).select_from(InvoiceModel).where(InvoiceModel.number.like(pattern))
        )
        return int(self._session.execute(stmt).scalar_one()) + 1


class SyncPaymentRepository:
    """``application.payments.ports.PaymentRepository``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _refunds(self, payment_id: str) -> Sequence[RefundModel]:
        stmt = (
            select(RefundModel)
            .where(RefundModel.payment_id == payment_id)
            .order_by(RefundModel.refunded_at, RefundModel.id)
        )
        return self._session.execute(stmt).scalars().all()

    def _hydrate(self, row: PaymentModel) -> Payment:
        return payment_to_domain(row, refunds=self._refunds(row.id))

    def get(self, payment_id: str) -> Payment | None:
        row = self._session.get(PaymentModel, payment_id)
        return self._hydrate(row) if row is not None else None

    def save(self, payment: Payment) -> None:
        """Upsert the payment, then append any refund it gained.

        Refunds are insert-only. A refund row is a record that money left the
        business; rewriting one would make the audit trail negotiable.
        """
        row = self._session.get(PaymentModel, payment.id)
        if row is None:
            self._session.add(payment_to_row(payment))
        else:
            payment_apply(row, payment)

        known = set(
            self._session.execute(
                select(RefundModel.id).where(RefundModel.payment_id == payment.id)
            )
            .scalars()
            .all()
        )
        for entry in payment.refunds:
            if entry.refund_id not in known:
                self._session.add(
                    refund_to_row(entry, payment_id=payment.id, user_id=payment.user_id)
                )
        self._session.flush()

    def find_by_digest(self, digest: str) -> Payment | None:
        """The duplicate-receipt guard.

        Goes through the digest table rather than through a JSON path into
        ``payments.proof``: the digest table has a primary-key index, and the
        JSON path would be a sequential scan on the busiest table here.
        """
        row = self._session.get(ReceiptDigestModel, digest)
        if row is None or row.payment_id is None:
            return None
        payment = self._session.get(PaymentModel, row.payment_id)
        return self._hydrate(payment) if payment is not None else None

    def find_by_gateway_reference(self, *, gateway_key: str, reference: str) -> Payment | None:
        stmt = select(PaymentModel).where(
            PaymentModel.gateway_key == gateway_key,
            PaymentModel.gateway_reference == reference,
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return self._hydrate(row) if row is not None else None

    def list_for_user(self, user_id: int, *, limit: int, offset: int = 0) -> Sequence[Payment]:
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.user_id == user_id)
            .order_by(PaymentModel.submitted_at.desc().nullslast(), PaymentModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._hydrate(row) for row in self._session.execute(stmt).scalars().all()]

    def in_state(
        self, state: PaymentState, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Payment]:
        """Oldest first, deliberately.

        This feeds the review queue. Newest-first would let a busy day bury the
        customer who has been waiting longest, which is precisely the customer
        who is about to open a ticket.
        """
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.state == state.value)
            .order_by(PaymentModel.submitted_at.asc().nullsfirst(), PaymentModel.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return [self._hydrate(row) for row in self._session.execute(stmt).scalars().all()]

    def count_in_state(self, state: PaymentState) -> int:
        stmt = (
            select(func.count()).select_from(PaymentModel).where(PaymentModel.state == state.value)
        )
        return int(self._session.execute(stmt).scalar_one())

    def expiring_before(self, now: datetime, *, limit: int = 100) -> Sequence[Payment]:
        """Unsettled payments whose window has closed.

        Only unsettled states are considered: an approved payment that happens
        to carry an old ``expires_at`` must never be swept into 'expired'.
        """
        unsettled = (
            PaymentState.DRAFT.value,
            PaymentState.AWAITING_PROOF.value,
            PaymentState.PENDING_REVIEW.value,
            PaymentState.PENDING_GATEWAY.value,
        )
        stmt = (
            select(PaymentModel)
            .where(
                PaymentModel.expires_at.is_not(None),
                PaymentModel.expires_at < now,
                PaymentModel.state.in_(unsettled),
            )
            .order_by(PaymentModel.expires_at.asc())
            .limit(limit)
        )
        return [self._hydrate(row) for row in self._session.execute(stmt).scalars().all()]


class SyncReceiptDigestRepository:
    """Writes the duplicate-receipt guard.

    `SyncPaymentRepository.find_by_digest` has always *read* this table and
    nothing ever wrote a row, so the lookup could only ever miss and the same
    receipt could be submitted against as many payments as a customer liked.

    Claiming is an INSERT and the primary key is what makes it atomic. A
    select-then-insert would let two submissions of the same photo, in the same
    second, both pass the check.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

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
        """Record the digest. Raises ``IntegrityError`` if already claimed."""
        self._session.add(
            ReceiptDigestModel(
                digest=digest,
                payment_id=payment_id,
                user_id=user_id,
                reference=reference,
                method=method,
                seen_at=seen_at,
            )
        )
        try:
            # Flushed here so the violation surfaces as a failure of *this*
            # call, inside the same transaction as attach_proof, rather than at
            # an unrelated commit later.
            self._session.flush()
        except IntegrityError as exc:
            raise DuplicateReceipt(reference=reference, existing_payment=payment_id) from exc


class SyncWalletRepository:
    """``application.payments.ports.WalletRepository``.

    There is no balance column. The wallet is rebuilt from its ledger on every
    read, so the balance cannot drift away from the entries that justify it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(self, user_id: int) -> Wallet:
        """An empty ledger is a valid wallet, so nothing is ever created here."""
        stmt = (
            select(WalletEntryModel)
            .where(WalletEntryModel.user_id == user_id)
            .order_by(WalletEntryModel.occurred_at, WalletEntryModel.id)
        )
        rows = self._session.execute(stmt).scalars().all()
        return wallet_to_domain(user_id, rows)

    def save(self, wallet: Wallet) -> None:
        """Append whatever the aggregate gained since it was loaded.

        Existing entries are never rewritten. A ledger line that can be edited
        after the fact is not a ledger.
        """
        known = set(
            self._session.execute(
                select(WalletEntryModel.id).where(WalletEntryModel.user_id == wallet.id)
            )
            .scalars()
            .all()
        )
        for entry in wallet.entries:
            if entry.entry_id not in known:
                self._session.add(wallet_entry_to_row(entry, user_id=wallet.id))
        self._session.flush()

    def lock(self, user_id: int) -> None:
        """Serialise concurrent spends by the same customer.

        Without this, two simultaneous purchases can both read a balance of
        100,000, both pass the affordability check, and both succeed - and the
        ledger ends up with a negative balance that the CHECK constraint will
        reject at the worst possible moment. The lock is transaction-scoped, so
        it is released by commit or rollback with nothing to clean up.
        """
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)"),
            {"namespace": WALLET_LOCK_NAMESPACE % 2_147_483_647, "user_id": user_id},
        )


def _unused_not_found() -> None:  # pragma: no cover - keeps the import honest
    raise NotFoundError("unreachable")


__all__ = [
    "WALLET_LOCK_NAMESPACE",
    "SyncInvoiceRepository",
    "SyncPaymentRepository",
    "SyncWalletRepository",
]
