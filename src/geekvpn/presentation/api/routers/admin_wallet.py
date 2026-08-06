"""Customer wallets, seen and corrected from the admin panel.

The wallet is an append-only ledger: there is no "set the balance to X". The
only way to change it here is ``adjust``, which writes a signed entry with a
reason and the acting administrator attached, so every Toman that appears or
disappears has a sentence next to it explaining why. A balance that could be
overwritten silently is a balance nobody can audit.

Two consequences show up in this file:

* ``/adjust`` demands a Persian reason and an ``Idempotency-Key``. A retried
  request that credited twice would be indistinguishable from generosity.
* ``/integrity`` re-adds the whole ledger and compares it with the stored
  balance. It is exposed deliberately: when a customer disputes their balance,
  the first honest answer is whether the ledger still sums to it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.payments.enums import TransactionKind
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

router = APIRouter(prefix="/admin/wallets", tags=["wallet"])


class AdjustBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signedAmount: int = Field(
        description="Positive credits the wallet, negative debits it. Zero is refused.",
    )
    reasonFa: str = Field(
        min_length=5,
        max_length=512,
        description="Stored on the ledger entry forever, and readable by the customer.",
    )


def _entry_dict(entry: Any) -> dict[str, Any]:
    return {
        "entryId": entry.entry_id,
        "kind": entry.kind.value,
        "amount": entry.amount,
        "balanceAfter": entry.balance_after,
        "occurredAt": entry.occurred_at.isoformat(),
        "descriptionFa": entry.description_fa,
        "reference": entry.reference,
        "actorId": entry.actor_id,
        "isCredit": entry.is_credit,
    }


@router.get(
    "/{user_id}",
    summary="A customer's wallet balance",
    dependencies=[Depends(requires(Permission.WALLET_READ))],
)
async def get_balance(user_id: int, container: ContainerDep, admin: CurrentAdmin) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return {"userId": user_id, "balance": scope.wallet.balance(user_id).amount}

    return await read_scope(container, work)


@router.get(
    "/{user_id}/statement",
    summary="The ledger behind the balance",
    dependencies=[Depends(requires(Permission.WALLET_READ))],
)
async def get_statement(
    user_id: int,
    container: ContainerDep,
    admin: CurrentAdmin,
    kind: TransactionKind | None = None,
    page: PageQuery = 1,
) -> dict[str, Any]:
    offset = (page - 1) * ADMIN_PAGE_SIZE

    def work(scope: SyncScope) -> dict[str, Any]:
        statement = scope.wallet.statement(user_id, limit=ADMIN_PAGE_SIZE, offset=offset, kind=kind)
        return {
            "items": [_entry_dict(e) for e in statement.entries],
            "page": page,
            "pageSize": statement.page_size,
            "total": statement.total,
            "balance": statement.balance,
            "hasMore": statement.has_more,
        }

    return await read_scope(container, work)


@router.get(
    "/{user_id}/integrity",
    summary="Does the ledger still sum to the stored balance?",
    dependencies=[Depends(requires(Permission.WALLET_READ))],
)
async def verify_integrity(
    user_id: int, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        intact = scope.wallet.verify_integrity(user_id)
        return {
            "userId": user_id,
            "intact": intact,
            "messageFa": (
                "موجودی با جمع تراکنش‌ها همخوانی دارد."
                if intact
                else "موجودی با جمع تراکنش‌ها همخوانی ندارد و باید بررسی شود."
            ),
        }

    return await read_scope(container, work)


@router.post(
    "/{user_id}/adjust",
    status_code=status.HTTP_201_CREATED,
    summary="Credit or debit a wallet, with a reason on the record",
    dependencies=[Depends(requires(Permission.WALLET_ADJUST))],
)
async def adjust_wallet(
    user_id: int,
    payload: AdjustBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"wallet.adjust:{user_id}")

    def work(scope: SyncScope) -> dict[str, Any]:
        entry = scope.wallet.adjust(
            user_id=user_id,
            signed_amount=payload.signedAmount,
            actor_id=actor,
            reason_fa=payload.reasonFa,
        )
        return {
            "entry": _entry_dict(entry),
            "balance": scope.wallet.balance(user_id).amount,
        }

    return await mutate_scope(container, work)


__all__ = ["router"]
