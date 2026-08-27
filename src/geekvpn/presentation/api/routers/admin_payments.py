"""Manual payment review, and refunds, for the admin panel.

Why this file looks different from ``admin_catalog.py``
------------------------------------------------------
Every service behind these routes is **synchronous** (see the long note at the
top of ``repositories/sync_payments.py``). A coroutine cannot call
``PaymentReviewService.approve``, so each handler hands the whole use case to a
worker thread through ``run_in_threadpool`` and owns the transaction around it:
commit on success, roll back on any exception, close always. The repositories
never commit - that rule is what makes "approve, credit the wallet, write the
audit row" one atomic step instead of three hopeful ones.

Money rules encoded here rather than trusted to the caller
----------------------------------------------------------
* Approving, rejecting and refunding are **mutations that must not replay**. A
  reviewer double-clicking "approve" on a slow connection must not credit a
  wallet twice, so an ``Idempotency-Key`` header is mandatory and is claimed in
  Redis with ``add_if_absent`` *before* the work starts. A repeat of the same
  key is answered 409, not silently re-executed.
* A rejection needs a real Persian reason (5 characters minimum). "no" is not a
  reason a customer can act on, and this is the message they receive verbatim.
* The reviewer is identified by their linked Telegram id, and the route refuses
  to act when there is none. The payment services type ``actor_id`` as ``int``
  while an administrator's identity is a ``uuid.UUID``, and ``AdminModel`` has
  no integer surrogate key. Fabricating a number would put a fictional identity
  on a money movement forever, so the request fails with an explanation
  instead. ``SyncAuditLog`` refuses the same coercion for the same reason.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Response, status
from pydantic import ConfigDict, Field
from sqlalchemy import select

from geekvpn.application.payments.refund_service import RefundRequest
from geekvpn.application.payments.review_service import ApprovalRequest
from geekvpn.domain.base.errors import ConflictError, NotFoundError
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.payments.enums import PaymentState, RefundDestination, RefundReason
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.persistence.models.payments import (
    CardAccountModel,
    CryptoAccountModel,
)
from geekvpn.infrastructure.persistence.repositories.sync_directory import Person
from geekvpn.presentation.api.admin_common import (
    ADMIN_PAGE_SIZE,
    ActorId,
    IdempotencyKey,
    PageQuery,
    claim_idempotency,
    mutate_scope,
    read_scope,
)
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import CurrentAdmin, requires

router = APIRouter(prefix="/admin/payments", tags=["payments"])

#: Long enough for a photo over a slow route, short enough that a stuck
#: fetch cannot hold an admin request open.
TELEGRAM_TIMEOUT_SECONDS = 15.0

# -- request bodies ---------------------------------------------------------


class ApproveRequestBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    actualAmount: int | None = Field(
        default=None,
        ge=0,
        description=(
            "What the reviewer read off the receipt, in Toman. Omit when it "
            "matches the invoice, which is the common case."
        ),
    )


class RejectRequestBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    reasonFa: str = Field(
        min_length=5,
        max_length=512,
        description="Shown to the customer as-is, so it must be a usable sentence.",
    )


class RefundRequestBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    reason: RefundReason
    noteFa: str = Field(min_length=5, max_length=512)
    amount: int | None = Field(
        default=None,
        gt=0,
        description="Omit for a full refund of whatever is still refundable.",
    )
    destination: RefundDestination = RefundDestination.WALLET


# -- serialisation ----------------------------------------------------------


def _proof_dict(payment: Any) -> dict[str, Any] | None:
    proof = payment.proof
    if proof is None:
        return None
    return {
        "method": proof.method.value,
        "reference": proof.reference,
        "digest": proof.digest,
        "submittedAt": proof.submitted_at.isoformat(),
        "fileId": proof.file_id,
        "network": proof.network,
        "noteFa": proof.note_fa,
    }


def _with_people(scope: SyncScope, payments: Sequence[Any], *, now: Any = None) -> list[dict[str, Any]]:
    """Label a page of payments with who made them.

    One lookup for the page, the same as the ticket queue. This is the screen
    where money is approved, and approving the wrong customer's transfer is the
    mistake a raw id invites.
    """
    people = scope.directory.by_telegram_ids(payment.user_id for payment in payments)
    return [
        _payment_dict(payment, now=now, person=people.get(payment.user_id))
        for payment in payments
    ]


def _payment_dict(
    payment: Any, *, now: Any = None, person: Person | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": payment.id,
        "invoiceId": payment.invoice_id,
        "userId": payment.user_id,
        "customerName": person.display_name if person else None,
        "customerUsername": person.username if person else None,
        "method": payment.method.value,
        "state": payment.state.value,
        "amount": payment.amount.amount,
        "captured": payment.captured,
        "refundedTotal": payment.refunded_total,
        "refundable": payment.refundable,
        "isRefundable": payment.is_refundable,
        "gatewayKey": payment.gateway_key,
        "gatewayReference": payment.gateway_reference,
        "expiresAt": payment.expires_at.isoformat() if payment.expires_at else None,
        "settledAt": payment.settled_at.isoformat() if payment.settled_at else None,
        "reviewedAt": payment.reviewed_at.isoformat() if payment.reviewed_at else None,
        "reviewedBy": payment.reviewed_by,
        "rejectionReasonFa": payment.rejection_reason_fa,
        "failureReason": payment.failure_reason,
        "proof": _proof_dict(payment),
        "refunds": [
            {
                "refundId": entry.refund_id,
                "amount": entry.amount,
                "reason": entry.reason.value,
                "destination": entry.destination.value,
                "noteFa": entry.note_fa,
                "refundedAt": entry.refunded_at.isoformat(),
                "actorId": entry.actor_id,
            }
            for entry in payment.refunds
        ],
    }
    if now is not None:
        # How long this customer has been waiting is the most useful column in
        # the queue, and only the server knows "now" authoritatively.
        data["waitingMinutes"] = payment.waiting_minutes(now)
    return data


# -- routes -----------------------------------------------------------------


@router.get(
    "",
    summary="The review queue, or any other payment state",
    dependencies=[Depends(requires(Permission.PAYMENTS_READ))],
)
async def list_payments(
    container: ContainerDep,
    admin: CurrentAdmin,
    state: PaymentState = PaymentState.PENDING_REVIEW,
    page: PageQuery = 1,
) -> dict[str, Any]:
    offset = (page - 1) * ADMIN_PAGE_SIZE
    now = container.clock.now()

    def work(scope: SyncScope) -> dict[str, Any]:
        rows = scope.payments.in_state(state, limit=ADMIN_PAGE_SIZE, offset=offset)
        return {
            "items": _with_people(scope, rows, now=now),
            "page": page,
            "pageSize": ADMIN_PAGE_SIZE,
            "total": scope.payments.count_in_state(state),
        }

    return await read_scope(container, work)


# -- destination cards -------------------------------------------------------
#
# The card-to-card flow reads its destination from `billing_card_accounts`,
# deliberately: "cards rotate constantly in the Iranian market, and a rotation
# must be something support can do in the panel, not a deployment" - the
# comment in `sync_scope` that describes a panel screen which did not exist.
# There was no endpoint and no UI, so the only way to take a payment was to
# write a row by hand, and a fresh install could not sell at all.


class CardBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    holder_fa: str = Field(min_length=1, max_length=128)
    bank_fa: str = Field(min_length=1, max_length=64)
    #: Digits only. Stored as typed; the bot formats it for the customer.
    card_number: str = Field(pattern=r"^\d{16,19}$")
    sheba: str | None = Field(default=None, max_length=26)
    #: The bot offers the lowest sort order that is active, so this is how a
    #: card is rotated without deleting the one it replaces.
    sort_order: int = 0
    active: bool = True
    daily_limit: int | None = Field(default=None, gt=0)
    #: Whose card this is. Null is the platform's own.
    #:
    #: A reseller's customer transfers to the reseller's card - the reseller has
    #: already bought the package out of their credit, so money arriving on ours
    #: for it would charge twice for one service.
    reseller_id: uuid.UUID | None = None


class CardPatchBody(ApiModel):
    """A real PATCH: every field optional, only what is sent is applied.

    Separate from `CardBody` rather than making that one's fields optional,
    because creating a card without a number is not a thing anybody should be
    able to ask for.
    """

    model_config = ConfigDict(extra="forbid")

    holder_fa: str | None = Field(default=None, min_length=1, max_length=128)
    bank_fa: str | None = Field(default=None, min_length=1, max_length=64)
    card_number: str | None = Field(default=None, pattern=r"^\d{16,19}$")
    sheba: str | None = Field(default=None, max_length=26)
    sort_order: int | None = None
    active: bool | None = None
    daily_limit: int | None = Field(default=None, gt=0)


#: Request field to column. Spelled out rather than derived, so a rename on
#: either side is a failing test rather than a silent no-op.
_CARD_FIELDS: dict[str, str] = {
    "holder_fa": "holder_fa",
    "bank_fa": "bank_fa",
    "card_number": "card_number",
    "sheba": "sheba",
    "sort_order": "sort_order",
    "active": "active",
    "daily_limit": "daily_limit",
}


class CryptoBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Stored readable. It is public by definition - it is what a customer is
    #: told to send money to.
    address: str = Field(min_length=8, max_length=128)
    network: str = Field(min_length=2, max_length=32)
    asset: str = Field(default="USDT", max_length=16)
    sort_order: int = 0
    active: bool = True
    reseller_id: uuid.UUID | None = None


class CryptoPatchBody(ApiModel):
    """A real PATCH, like the card one: only what is sent is applied."""

    model_config = ConfigDict(extra="forbid")

    address: str | None = Field(default=None, min_length=8, max_length=128)
    network: str | None = Field(default=None, min_length=2, max_length=32)
    asset: str | None = Field(default=None, max_length=16)
    sort_order: int | None = None
    active: bool | None = None


def _crypto_dict(row: CryptoAccountModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "address": row.address,
        "network": row.network,
        "asset": row.asset,
        "active": row.active,
        "sortOrder": row.sort_order,
        "resellerId": None if row.reseller_id is None else str(row.reseller_id),
    }


def _card_dict(card: CardAccountModel) -> dict[str, Any]:
    return {
        "id": card.id,
        "holderFa": card.holder_fa,
        "bankFa": card.bank_fa,
        "cardNumber": card.card_number,
        "sheba": card.sheba,
        "active": card.active,
        "sortOrder": card.sort_order,
        "dailyLimit": card.daily_limit,
        "resellerId": None if card.reseller_id is None else str(card.reseller_id),
    }


@router.get(
    "/cards",
    summary="Destination cards for the card-to-card flow",
    dependencies=[Depends(requires(Permission.PAYMENTS_READ))],
)
async def list_cards(
    container: ContainerDep, reseller_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Every card, or one shop's.

    Without the filter this returns the platform's cards *and* every
    reseller's, which is right for an operator auditing them and wrong for the
    drawer that edits one reseller - so the caller says which.
    """

    def work(scope: SyncScope) -> list[dict[str, Any]]:
        stmt = select(CardAccountModel)
        if reseller_id is not None:
            stmt = stmt.where(CardAccountModel.reseller_id == reseller_id)
        rows = (
            scope.session.execute(
                stmt.order_by(CardAccountModel.sort_order, CardAccountModel.id)
            )
            .scalars()
            .all()
        )
        return [_card_dict(row) for row in rows]

    return await read_scope(container, work)


@router.get(
    "/crypto",
    summary="Destination crypto addresses",
    dependencies=[Depends(requires(Permission.PAYMENTS_READ))],
)
async def list_crypto(
    container: ContainerDep, reseller_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    def work(scope: SyncScope) -> list[dict[str, Any]]:
        stmt = select(CryptoAccountModel)
        if reseller_id is not None:
            stmt = stmt.where(CryptoAccountModel.reseller_id == reseller_id)
        rows = (
            scope.session.execute(
                stmt.order_by(CryptoAccountModel.sort_order, CryptoAccountModel.id)
            )
            .scalars()
            .all()
        )
        return [_crypto_dict(row) for row in rows]

    return await read_scope(container, work)


@router.post(
    "/crypto",
    status_code=status.HTTP_201_CREATED,
    summary="Add a destination crypto address",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def create_crypto(
    payload: CryptoBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label="crypto.create")

    def work(scope: SyncScope) -> dict[str, Any]:
        existing = scope.session.execute(
            select(CryptoAccountModel).where(
                CryptoAccountModel.address == payload.address,
                CryptoAccountModel.network == payload.network,
            )
        ).scalars().first()
        if existing is not None:
            raise ConflictError("این آدرس روی همین شبکه قبلاً ثبت شده است.")

        row = CryptoAccountModel(
            id=uuid.uuid4().hex,
            address=payload.address,
            network=payload.network,
            asset=payload.asset,
            active=payload.active,
            sort_order=payload.sort_order,
            reseller_id=payload.reseller_id,
        )
        scope.session.add(row)
        scope.session.flush()
        return _crypto_dict(row)

    return await mutate_scope(container, work)


@router.patch(
    "/crypto/{crypto_id}",
    summary="Edit an address, or retire it",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def update_crypto(
    crypto_id: str,
    payload: CryptoPatchBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"crypto.update:{crypto_id}")

    def work(scope: SyncScope) -> dict[str, Any]:
        row = scope.session.get(CryptoAccountModel, crypto_id)
        if row is None:
            raise NotFoundError("این آدرس پیدا نشد.")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        scope.session.flush()
        return _crypto_dict(row)

    return await mutate_scope(container, work)


@router.post(
    "/cards",
    status_code=status.HTTP_201_CREATED,
    summary="Add a destination card",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def create_card(
    payload: CardBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label="card.create")

    def work(scope: SyncScope) -> dict[str, Any]:
        existing = scope.session.execute(
            select(CardAccountModel).where(
                CardAccountModel.card_number == payload.card_number
            )
        ).scalars().first()
        if existing is not None:
            raise ConflictError("این شماره کارت قبلاً ثبت شده است.")

        card = CardAccountModel(
            id=uuid.uuid4().hex,
            holder_fa=payload.holder_fa,
            bank_fa=payload.bank_fa,
            card_number=payload.card_number,
            sheba=payload.sheba,
            active=payload.active,
            sort_order=payload.sort_order,
            daily_limit=payload.daily_limit,
            reseller_id=payload.reseller_id,
        )
        scope.session.add(card)
        scope.session.flush()
        return _card_dict(card)

    return await mutate_scope(container, work)


@router.patch(
    "/cards/{card_id}",
    summary="Edit a card, or retire it",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def update_card(
    card_id: str,
    payload: CardPatchBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"card.update:{card_id}")

    def work(scope: SyncScope) -> dict[str, Any]:
        card = scope.session.get(CardAccountModel, card_id)
        if card is None:
            raise NotFoundError("این کارت پیدا نشد.")
        # Only what was sent. It is a PATCH, and it took a whole `CardBody` -
        # so retiring a card meant resending its number, its holder and its
        # bank, and a caller that sent only `active` got a 422.
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(card, _CARD_FIELDS[field], value)
        scope.session.flush()
        return _card_dict(card)

    return await mutate_scope(container, work)


# Declared before `/{payment_id}`, and it has to stay that way: FastAPI
# matches in declaration order, so a literal path that comes after a
# parameterised one on the same prefix is unreachable. It was, and the
# symptom read like a database fault - creating a card worked, listing them
# returned nothing, and adding the same card again said it already existed.
@router.get(
    "/{payment_id}",
    summary="One payment, with its receipt and refund history",
    dependencies=[Depends(requires(Permission.PAYMENTS_READ))],
)
async def get_payment(
    payment_id: str,
    container: ContainerDep,
    admin: CurrentAdmin,
) -> dict[str, Any]:
    now = container.clock.now()

    def work(scope: SyncScope) -> dict[str, Any]:
        payment = scope.payments.get(payment_id)
        if payment is None:
            raise NotFoundError("این پرداخت پیدا نشد.", payment_id=payment_id)
        return _payment_dict(
            payment,
            now=now,
            person=scope.directory.by_telegram_ids([payment.user_id]).get(payment.user_id),
        )

    return await read_scope(container, work)


@router.post(
    "/{payment_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve a manually-paid payment",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def approve_payment(
    payment_id: str,
    payload: ApproveRequestBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"payment.approve:{payment_id}")
    request = ApprovalRequest(
        payment_id=payment_id, actor_id=actor, actual_amount=payload.actualAmount
    )

    def work(scope: SyncScope) -> dict[str, Any]:
        return _payment_dict(scope.review.approve(request))

    return await mutate_scope(container, work)


@router.post(
    "/{payment_id}/reject",
    status_code=status.HTTP_200_OK,
    summary="Reject a payment with a reason the customer will read",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def reject_payment(
    payment_id: str,
    payload: RejectRequestBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"payment.reject:{payment_id}")

    def work(scope: SyncScope) -> dict[str, Any]:
        return _payment_dict(
            scope.review.reject(payment_id=payment_id, actor_id=actor, reason_fa=payload.reasonFa)
        )

    return await mutate_scope(container, work)


@router.post(
    "/{payment_id}/request-proof",
    status_code=status.HTTP_200_OK,
    summary="Ask the customer for a clearer receipt",
    dependencies=[Depends(requires(Permission.PAYMENTS_APPROVE))],
)
async def request_better_proof(
    payment_id: str,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"payment.proof:{payment_id}")

    def work(scope: SyncScope) -> dict[str, Any]:
        return _payment_dict(
            scope.review.request_better_proof(payment_id=payment_id, actor_id=actor)
        )

    return await mutate_scope(container, work)


@router.post(
    "/{payment_id}/refund",
    status_code=status.HTTP_200_OK,
    summary="Refund a settled payment, to the wallet by default",
    dependencies=[Depends(requires(Permission.ORDERS_REFUND))],
)
async def refund_payment(
    payment_id: str,
    payload: RefundRequestBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"payment.refund:{payment_id}")
    request = RefundRequest(
        payment_id=payment_id,
        actor_id=actor,
        reason=payload.reason,
        note_fa=payload.noteFa,
        amount=payload.amount,
        destination=payload.destination,
    )

    def work(scope: SyncScope) -> dict[str, Any]:
        outcome = scope.refunds.refund(request)
        return {
            "payment": _payment_dict(outcome.payment),
            "refundId": outcome.entry.refund_id,
            "amount": outcome.entry.amount,
            "destination": outcome.destination.value,
            "walletCredited": outcome.wallet_credited,
            "fullyRefunded": outcome.fully_refunded,
            "messageFa": outcome.message_fa,
        }

    return await mutate_scope(container, work)


@router.get(
    "/{payment_id}/receipt",
    summary="The receipt image the customer sent, proxied from Telegram",
    dependencies=[Depends(requires(Permission.PAYMENTS_READ))],
    response_class=Response,
)
async def payment_receipt(
    payment_id: str,
    container: ContainerDep,
    admin: CurrentAdmin,
) -> Response:
    """Approving a transfer you cannot see is a signature on a blank page.

    The proof carries a Telegram file id and nothing else. The admin panel has
    no bot token and must not be given one, so the image was unreachable and an
    operator had to approve on trust - or open Telegram, find the customer, and
    scroll.

    The file id is read from the payment rather than accepted from the caller:
    a file id is a bearer token for whatever it points at, and taking one from
    the client would turn this into a way to read any file the bot can see.
    """

    def work(scope: SyncScope) -> str | None:
        payment = scope.payments.get(payment_id)
        if payment is None:
            raise NotFoundError("این پرداخت پیدا نشد.")
        return payment.proof.file_id if payment.proof else None

    file_id = await read_scope(container, work)
    if not file_id:
        raise NotFoundError("برای این پرداخت رسیدی ثبت نشده است.")

    token = container.settings.telegram.bot_token.get_secret_value()
    if not token:
        raise NotFoundError("توکن ربات تنظیم نشده، بنابراین رسید قابل دریافت نیست.")

    async with httpx.AsyncClient(timeout=TELEGRAM_TIMEOUT_SECONDS) as client:
        described = await client.get(
            f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}
        )
        path = (described.json().get("result") or {}).get("file_path") if described.is_success else None
        if not path:
            raise NotFoundError("تلگرام این رسید را برنگرداند. ممکن است منقضی شده باشد.")

        image = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
        if not image.is_success:
            raise NotFoundError("دریافت رسید از تلگرام ناموفق بود.")

    return Response(
        content=image.content,
        media_type=image.headers.get("content-type", "image/jpeg"),
        # A receipt carries a bank card number. It is fetched fresh every time
        # rather than left in a browser cache for whoever uses the machine next.
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["router"]
