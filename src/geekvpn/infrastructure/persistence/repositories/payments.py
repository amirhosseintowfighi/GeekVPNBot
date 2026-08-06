"""Billing repositories: invoices, payments, wallet, receipts, card accounts.

The wallet repository has no ``update``. A balance is never written; it is
rebuilt from the ledger every time it is asked for. That costs a query and buys
the one property this system cannot trade away: the balance always equals the
sum of the entries, because there is nowhere else for it to live.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.payments.enums import PaymentState
from geekvpn.domain.payments.invoice import Invoice
from geekvpn.domain.payments.payment import Payment
from geekvpn.domain.payments.wallet import LedgerEntry, Wallet
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
    CardAccountModel,
    InvoiceModel,
    PaymentModel,
    ReceiptDigestModel,
    RefundModel,
    WalletEntryModel,
)

#: Everything an operator still has to look at.
_AWAITING_REVIEW = (
    PaymentState.PENDING_REVIEW.value,
    PaymentState.AWAITING_PROOF.value,
)


class SqlAlchemyInvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, invoice_id: str) -> Invoice | None:
        row = await self._session.get(InvoiceModel, invoice_id)
        return invoice_to_domain(row) if row else None

    async def get_by_number(self, number: str) -> Invoice | None:
        stmt = select(InvoiceModel).where(InvoiceModel.number == number)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return invoice_to_domain(row) if row else None

    async def list_for_user(
        self, user_id: int, *, limit: int = 20, offset: int = 0
    ) -> Sequence[Invoice]:
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.user_id == user_id)
            .order_by(InvoiceModel.issued_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [invoice_to_domain(row) for row in rows]

    async def list_overdue(self, *, now: datetime, limit: int = 200) -> Sequence[Invoice]:
        stmt = (
            select(InvoiceModel)
            .where(
                InvoiceModel.state == "open",
                InvoiceModel.due_at.is_not(None),
                InvoiceModel.due_at <= now,
            )
            .order_by(InvoiceModel.due_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [invoice_to_domain(row) for row in rows]

    async def next_sequence(self, *, prefix: str) -> int:
        """How many invoice numbers already share this prefix.

        Callers turn this into the next number. It is a count rather than a
        sequence object because invoice numbers restart each Jalali year, and a
        Postgres sequence has no idea when that is.
        """
        stmt = (
            select(func.count())
            .select_from(InvoiceModel)
            .where(InvoiceModel.number.like(f"{prefix}%"))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add(self, invoice: Invoice) -> None:
        self._session.add(invoice_to_row(invoice))
        await self._session.flush()

    async def update(self, invoice: Invoice) -> None:
        row = await self._session.get(InvoiceModel, invoice.id)
        if row is None:
            raise NotFoundError("Invoice not found.", invoice_id=invoice.id)
        invoice_apply(row, invoice)
        await self._session.flush()


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _refunds(self, payment_id: str) -> Sequence[RefundModel]:
        stmt = (
            select(RefundModel)
            .where(RefundModel.payment_id == payment_id)
            .order_by(RefundModel.refunded_at, RefundModel.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, payment_id: str) -> Payment | None:
        row = await self._session.get(PaymentModel, payment_id)
        if row is None:
            return None
        return payment_to_domain(row, refunds=await self._refunds(payment_id))

    async def list_for_invoice(self, invoice_id: str) -> Sequence[Payment]:
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.invoice_id == invoice_id)
            .order_by(PaymentModel.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [payment_to_domain(row, refunds=await self._refunds(row.id)) for row in rows]

    async def list_for_user(
        self, user_id: int, *, limit: int = 20, offset: int = 0
    ) -> Sequence[Payment]:
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.user_id == user_id)
            .order_by(PaymentModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [payment_to_domain(row, refunds=await self._refunds(row.id)) for row in rows]

    async def list_awaiting_review(self, *, limit: int = 25, offset: int = 0) -> Sequence[Payment]:
        """The operator queue, oldest first.

        Oldest first is not cosmetic: a receipt that has been waiting two hours
        is the one costing us a customer, and a newest-first queue is how it
        stays at the bottom forever.
        """
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.state == PaymentState.PENDING_REVIEW.value)
            .order_by(PaymentModel.submitted_at, PaymentModel.created_at)
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [payment_to_domain(row, refunds=await self._refunds(row.id)) for row in rows]

    async def count_awaiting_review(self) -> int:
        stmt = (
            select(func.count())
            .select_from(PaymentModel)
            .where(PaymentModel.state == PaymentState.PENDING_REVIEW.value)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_expired_unpaid(self, *, now: datetime, limit: int = 200) -> Sequence[Payment]:
        stmt = (
            select(PaymentModel)
            .where(
                PaymentModel.state.in_(_AWAITING_REVIEW),
                PaymentModel.expires_at.is_not(None),
                PaymentModel.expires_at <= now,
            )
            .order_by(PaymentModel.expires_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [payment_to_domain(row, refunds=await self._refunds(row.id)) for row in rows]

    async def add(self, payment: Payment) -> None:
        self._session.add(payment_to_row(payment))
        await self._session.flush()

    async def update(self, payment: Payment) -> None:
        row = await self._session.get(PaymentModel, payment.id)
        if row is None:
            raise NotFoundError("Payment not found.", payment_id=payment.id)
        payment_apply(row, payment)
        # Refunds are append-only, so only the ones we have never stored are
        # inserted. Rewriting them would rewrite history that an auditor reads.
        existing = {model.id for model in await self._refunds(payment.id)}
        for entry in payment.refunds:
            if entry.refund_id not in existing:
                self._session.add(
                    refund_to_row(entry, payment_id=payment.id, user_id=payment.user_id)
                )
        await self._session.flush()


class SqlAlchemyWalletRepository:
    """Ledger in, wallet out. There is no balance column to disagree with."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> Wallet:
        stmt = (
            select(WalletEntryModel)
            .where(WalletEntryModel.user_id == user_id)
            .order_by(WalletEntryModel.occurred_at, WalletEntryModel.id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return wallet_to_domain(user_id, rows)

    async def append(self, user_id: int, entry: LedgerEntry) -> None:
        self._session.add(wallet_entry_to_row(entry, user_id=user_id))
        await self._session.flush()

    async def save_new_entries(self, wallet: Wallet) -> None:
        """Persist whatever the aggregate gained since it was loaded."""
        stmt = select(WalletEntryModel.id).where(WalletEntryModel.user_id == wallet.id)
        known = set((await self._session.execute(stmt)).scalars().all())
        for entry in wallet.entries:
            if entry.entry_id not in known:
                self._session.add(wallet_entry_to_row(entry, user_id=wallet.id))
        await self._session.flush()

    async def balance_of(self, user_id: int) -> int:
        """Latest ``balance_after``, for list screens that need a number only.

        Cheaper than rebuilding the wallet, and safe because it reads the same
        derived column the ledger wrote - never an independently stored total.
        """
        stmt = (
            select(WalletEntryModel.balance_after)
            .where(WalletEntryModel.user_id == user_id)
            .order_by(WalletEntryModel.occurred_at.desc(), WalletEntryModel.id.desc())
            .limit(1)
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(value or 0)


class SqlAlchemyReceiptDigestRepository:
    """Duplicate-receipt guard.

    A digest is claimed with an INSERT and the uniqueness of the primary key is
    what makes the check atomic. A select-then-insert would let two operators
    approve the same photo in the same second.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, digest: str) -> ReceiptDigestModel | None:
        return await self._session.get(ReceiptDigestModel, digest)

    async def claim(
        self,
        digest: str,
        *,
        payment_id: str,
        user_id: int,
        reference: str,
        method: str,
        seen_at: datetime,
    ) -> None:
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
        await self._session.flush()


class SqlAlchemyCardAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self, *, active_only: bool = False) -> Sequence[CardAccountModel]:
        stmt: Select = select(CardAccountModel).order_by(
            CardAccountModel.sort_order, CardAccountModel.id
        )
        if active_only:
            stmt = stmt.where(CardAccountModel.active.is_(True))
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, card_id: str) -> CardAccountModel | None:
        return await self._session.get(CardAccountModel, card_id)


__all__ = [
    "SqlAlchemyCardAccountRepository",
    "SqlAlchemyInvoiceRepository",
    "SqlAlchemyPaymentRepository",
    "SqlAlchemyReceiptDigestRepository",
    "SqlAlchemyWalletRepository",
]
