"""Mappers between the billing tables and the billing aggregates.

Two rules shape everything here.

**The ledger is the truth.** A ``Wallet`` is rebuilt from its entries, never
from a stored balance, so ``balance_after`` on each row is a witness we can
audit rather than a number we trust.

**Denormalised columns are written, never read.** ``payments.refunded_total``
exists so the admin list can sort and filter without a join, but the aggregate
recomputes it from the refund rows on load. If the two ever disagree, the
ledger wins and the stale column is corrected on the next save.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    InvoiceState,
    PaymentMethod,
    PaymentState,
    RefundDestination,
    RefundReason,
    TransactionKind,
)
from geekvpn.domain.payments.invoice import Invoice, InvoiceLine
from geekvpn.domain.payments.payment import Payment, RefundEntry
from geekvpn.domain.payments.proof import PaymentProof
from geekvpn.domain.payments.wallet import LedgerEntry, Wallet
from geekvpn.infrastructure.persistence.models.payments import (
    InvoiceModel,
    PaymentModel,
    RefundModel,
    WalletEntryModel,
)

# -- invoice ---------------------------------------------------------------


def line_to_json(line: InvoiceLine) -> dict[str, Any]:
    return {
        "title_fa": line.title_fa,
        "amount": int(line.amount),
        "quantity": int(line.quantity),
        "detail_fa": line.detail_fa,
    }


def line_from_json(raw: dict[str, Any]) -> InvoiceLine:
    return InvoiceLine(
        title_fa=raw["title_fa"],
        amount=int(raw["amount"]),
        quantity=int(raw.get("quantity", 1)),
        detail_fa=raw.get("detail_fa"),
    )


def invoice_to_domain(model: InvoiceModel) -> Invoice:
    return Invoice(
        model.id,
        number=model.number,
        user_id=model.user_id,
        subject_fa=model.subject_fa,
        lines=[line_from_json(raw) for raw in (model.lines or [])],
        issued_at=model.issued_at,
        due_at=model.due_at,
        state=InvoiceState(model.state),
        paid_at=model.paid_at,
        paid_by_payment_id=model.paid_by_payment_id,
        metadata=dict(model.meta or {}),
    )


def invoice_apply(model: InvoiceModel, invoice: Invoice) -> InvoiceModel:
    """Copy an aggregate onto a row. Used for both insert and update.

    ``id``, ``number`` and ``user_id`` are deliberately not reassigned: they
    are set once at creation, and letting an update touch them would turn a
    bug in a use case into a silently re-keyed invoice.
    """
    model.state = invoice.state.value
    model.lines = [line_to_json(line) for line in invoice.lines]
    model.subtotal = int(invoice.subtotal)
    model.discount_total = int(invoice.discount_total)
    model.total = int(invoice.total)
    model.subject_fa = invoice.subject_fa
    model.issued_at = invoice.issued_at
    model.due_at = invoice.due_at
    model.paid_at = invoice.paid_at
    model.paid_by_payment_id = invoice.paid_by_payment_id
    model.meta = dict(invoice.metadata or {})
    return model


def invoice_to_row(invoice: Invoice) -> InvoiceModel:
    model = InvoiceModel(
        id=invoice.id,
        number=invoice.number,
        user_id=invoice.user_id,
    )
    return invoice_apply(model, invoice)


# -- proof -----------------------------------------------------------------


def proof_to_json(proof: PaymentProof) -> dict[str, Any]:
    return {
        "method": proof.method.value,
        "reference": proof.reference,
        "digest": proof.digest,
        # JSONB has no datetime type; ISO-8601 keeps the timezone, which a
        # POSIX timestamp would quietly drop.
        "submitted_at": proof.submitted_at.isoformat(),
        "file_id": proof.file_id,
        "network": proof.network,
        "note_fa": proof.note_fa,
    }


def proof_from_json(raw: dict[str, Any] | None) -> PaymentProof | None:
    if not raw:
        return None
    return PaymentProof(
        method=PaymentMethod(raw["method"]),
        reference=raw["reference"],
        digest=raw["digest"],
        submitted_at=datetime.fromisoformat(raw["submitted_at"]),
        file_id=raw.get("file_id"),
        network=raw.get("network"),
        note_fa=raw.get("note_fa"),
    )


# -- refunds ---------------------------------------------------------------


def refund_to_domain(model: RefundModel) -> RefundEntry:
    return RefundEntry(
        refund_id=model.id,
        amount=int(model.amount),
        reason=RefundReason(model.reason),
        destination=RefundDestination(model.destination),
        note_fa=model.note_fa,
        refunded_at=model.refunded_at,
        actor_id=model.actor_id,
    )


def refund_to_row(entry: RefundEntry, *, payment_id: str, user_id: int) -> RefundModel:
    return RefundModel(
        id=entry.refund_id,
        payment_id=payment_id,
        user_id=user_id,
        amount=int(entry.amount),
        reason=entry.reason.value,
        destination=entry.destination.value,
        note_fa=entry.note_fa,
        refunded_at=entry.refunded_at,
        actor_id=entry.actor_id,
    )


# -- payment ---------------------------------------------------------------


def payment_to_domain(model: PaymentModel, *, refunds: Sequence[RefundModel] = ()) -> Payment:
    """Rebuild a payment.

    ``refunds`` must be every refund row for this payment. Passing a partial
    list would make the aggregate believe more money is refundable than really
    is, so the repository loads them together rather than lazily.
    """
    return Payment(
        model.id,
        invoice_id=model.invoice_id,
        user_id=model.user_id,
        method=PaymentMethod(model.method),
        amount=Money(int(model.amount)),
        created_at=model.created_at,
        state=PaymentState(model.state),
        expires_at=model.expires_at,
        gateway_key=model.gateway_key,
        gateway_reference=model.gateway_reference,
        proof=proof_from_json(model.proof),
        captured=int(model.captured or 0),
        refunds=[refund_to_domain(row) for row in refunds],
        settled_at=model.settled_at,
        reviewed_at=model.reviewed_at,
        reviewed_by=model.reviewed_by,
        rejection_reason_fa=model.reason_fa,
        failure_reason=model.failure_reason,
        metadata=dict(model.meta or {}),
    )


def payment_apply(model: PaymentModel, payment: Payment) -> PaymentModel:
    model.state = payment.state.value
    model.method = payment.method.value
    model.amount = int(payment.amount.amount)
    model.captured = int(payment.captured)
    # Denormalised for the admin list; recomputed from the rows on load.
    model.refunded_total = int(payment.refunded_total)
    model.gateway_key = payment.gateway_key
    model.gateway_reference = payment.gateway_reference
    model.proof = proof_to_json(payment.proof) if payment.proof else None
    model.expires_at = payment.expires_at
    # The moment the customer handed us evidence, taken from the proof itself
    # so a re-submission moves the queue position honestly.
    model.submitted_at = payment.proof.submitted_at if payment.proof else None
    model.settled_at = payment.settled_at
    model.reviewed_at = payment.reviewed_at
    model.reviewed_by = payment.reviewed_by
    model.reason_fa = payment.rejection_reason_fa
    model.failure_reason = payment.failure_reason
    model.meta = dict(payment.metadata or {})
    return model


def payment_to_row(payment: Payment) -> PaymentModel:
    model = PaymentModel(
        id=payment.id,
        invoice_id=payment.invoice_id,
        user_id=payment.user_id,
    )
    return payment_apply(model, payment)


# -- wallet ----------------------------------------------------------------


def wallet_entry_to_domain(model: WalletEntryModel) -> LedgerEntry:
    return LedgerEntry(
        entry_id=model.id,
        kind=TransactionKind(model.kind),
        amount=int(model.amount),
        balance_after=int(model.balance_after),
        occurred_at=model.occurred_at,
        description_fa=model.description_fa,
        reference=model.reference,
        actor_id=model.actor_id,
    )


def wallet_entry_to_row(entry: LedgerEntry, *, user_id: int) -> WalletEntryModel:
    return WalletEntryModel(
        id=entry.entry_id,
        user_id=user_id,
        kind=entry.kind.value,
        amount=int(entry.amount),
        balance_after=int(entry.balance_after),
        occurred_at=entry.occurred_at,
        description_fa=entry.description_fa,
        reference=entry.reference,
        actor_id=entry.actor_id,
    )


def wallet_to_domain(user_id: int, models: Sequence[WalletEntryModel]) -> Wallet:
    """Rebuild a wallet from its ledger, oldest entry first.

    The order matters: ``balance_after`` is only meaningful in sequence, and a
    wallet built from newest-first rows would report the opening balance as the
    current one.
    """
    ordered = sorted(models, key=lambda row: (row.occurred_at, row.id))
    return Wallet(user_id, [wallet_entry_to_domain(row) for row in ordered])


__all__ = [
    "invoice_apply",
    "invoice_to_domain",
    "invoice_to_row",
    "line_from_json",
    "line_to_json",
    "payment_apply",
    "payment_to_domain",
    "payment_to_row",
    "proof_from_json",
    "proof_to_json",
    "refund_to_domain",
    "refund_to_row",
    "wallet_entry_to_domain",
    "wallet_entry_to_row",
    "wallet_to_domain",
]
