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

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from geekvpn.application.payments.refund_service import RefundRequest
from geekvpn.application.payments.review_service import ApprovalRequest
from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.payments.enums import PaymentState, RefundDestination, RefundReason
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import (
    ADMIN_PAGE_SIZE,
    ActorId,
    IdempotencyKey,
    PageQuery,
    claim_idempotency,
    mutate_scope,
    read_scope,
)
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import CurrentAdmin, requires

router = APIRouter(prefix="/admin/payments", tags=["payments"])

# -- request bodies ---------------------------------------------------------


class ApproveRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actualAmount: int | None = Field(
        default=None,
        ge=0,
        description=(
            "What the reviewer read off the receipt, in Toman. Omit when it "
            "matches the invoice, which is the common case."
        ),
    )


class RejectRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasonFa: str = Field(
        min_length=5,
        max_length=512,
        description="Shown to the customer as-is, so it must be a usable sentence.",
    )


class RefundRequestBody(BaseModel):
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


def _payment_dict(payment: Any, *, now: Any = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": payment.id,
        "invoiceId": payment.invoice_id,
        "userId": payment.user_id,
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
            "items": [_payment_dict(row, now=now) for row in rows],
            "page": page,
            "pageSize": ADMIN_PAGE_SIZE,
            "total": scope.payments.count_in_state(state),
        }

    return await read_scope(container, work)


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
        return _payment_dict(payment, now=now)

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


__all__ = ["router"]
