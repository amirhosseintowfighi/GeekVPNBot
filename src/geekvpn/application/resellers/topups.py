"""A reseller asking for credit, and an operator deciding whether it arrived.

The money moves through `ResellerService.adjust_credit` and nowhere else, so a
balance still only changes in one place and still writes a ledger row on the
way past. This adds the one thing that flow has no opinion about: a request
sitting between "I sent you money" and "your balance went up", with a person in
the middle.

A reseller's credit is not a customer wallet. There is no gateway, no cashback,
no refund policy - the reseller transfers money to the platform however the two
of them already arrange it, and what needs recording is the decision.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from geekvpn.application.resellers.ports import Clock
from geekvpn.application.resellers.service import TOPUP, ResellerService

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"

#: The smallest request worth an operator's attention. Not a policy about how
#: much a reseller must buy - it is a floor under accidental zeros and slips of
#: a keyboard, which is what an operator would otherwise spend their day
#: rejecting.
MIN_TOPUP = 10_000


class TopupNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class TopupView:
    id: uuid.UUID
    reseller_id: uuid.UUID
    reseller_name_fa: str
    amount: int
    note_fa: str | None
    receipt_file_id: str | None
    state: str
    created_at: datetime


class TopupRepository(Protocol):
    async def add(self, **fields: Any) -> uuid.UUID: ...

    async def get(self, topup_id: uuid.UUID) -> TopupView | None: ...

    async def list_pending(self, *, limit: int = 50) -> Sequence[TopupView]: ...

    async def list_for(
        self, reseller_id: uuid.UUID, *, limit: int = 20
    ) -> Sequence[TopupView]: ...

    async def decide(
        self,
        topup_id: uuid.UUID,
        *,
        state: str,
        decided_by: int | None,
        decided_at: datetime,
        reason_fa: str | None = None,
    ) -> None: ...


class ResellerTopups:
    def __init__(
        self,
        *,
        topups: TopupRepository,
        resellers: ResellerService,
        clock: Clock,
    ) -> None:
        self._topups = topups
        self._resellers = resellers
        self._clock = clock

    async def request(
        self,
        *,
        reseller_id: uuid.UUID,
        amount: int,
        note_fa: str | None = None,
        receipt_file_id: str | None = None,
    ) -> uuid.UUID:
        if amount < MIN_TOPUP:
            raise ValueError(f"Ask for at least {MIN_TOPUP} Toman.")
        # Confirms the reseller exists before writing a row that points at
        # them - and raises the same not-found the rest of this package does.
        await self._resellers.get(reseller_id)
        return await self._topups.add(
            id=uuid.uuid4(),
            reseller_id=reseller_id,
            amount=amount,
            note_fa=(note_fa or "").strip() or None,
            receipt_file_id=receipt_file_id,
            state=PENDING,
        )

    async def pending(self, *, limit: int = 50) -> Sequence[TopupView]:
        return await self._topups.list_pending(limit=limit)

    async def mine(self, reseller_id: uuid.UUID, *, limit: int = 20) -> Sequence[TopupView]:
        return await self._topups.list_for(reseller_id, limit=limit)

    async def approve(
        self, topup_id: uuid.UUID, *, decided_by: int | None = None
    ) -> TopupView:
        """Credit the balance, then record the decision.

        In that order. If the decision were written first and the credit then
        failed, the request would read as settled with no money behind it - and
        the reseller would be told to go and sell something they cannot pay for.
        """
        topup = await self._require_pending(topup_id)

        await self._resellers.adjust_credit(
            topup.reseller_id,
            amount=topup.amount,
            description_fa=f"شارژ حساب — {topup.note_fa}" if topup.note_fa else "شارژ حساب",
            actor_id=decided_by,
            kind=TOPUP,
        )
        await self._topups.decide(
            topup_id,
            state=APPROVED,
            decided_by=decided_by,
            decided_at=self._clock.now(),
        )
        return topup

    async def reject(
        self, topup_id: uuid.UUID, *, reason_fa: str = "", decided_by: int | None = None
    ) -> TopupView:
        topup = await self._require_pending(topup_id)
        await self._topups.decide(
            topup_id,
            state=REJECTED,
            decided_by=decided_by,
            decided_at=self._clock.now(),
            reason_fa=reason_fa.strip() or None,
        )
        return topup

    async def _require_pending(self, topup_id: uuid.UUID) -> TopupView:
        topup = await self._topups.get(topup_id)
        if topup is None or topup.state != PENDING:
            # Already decided counts as not found, deliberately: two operators
            # opening the same queue must not be able to credit one transfer
            # twice between them.
            raise TopupNotFound("No such request is waiting.")
        return topup


__all__ = [
    "APPROVED",
    "MIN_TOPUP",
    "PENDING",
    "REJECTED",
    "ResellerTopups",
    "TopupNotFound",
    "TopupRepository",
    "TopupView",
]
