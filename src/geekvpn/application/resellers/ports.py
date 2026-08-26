"""What the reseller service needs from the outside world."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.resellers.reseller import Reseller


class Clock(Protocol):
    """Time comes from a port, never from `datetime.now()`."""

    def now(self) -> datetime: ...


class LedgerEntry(Protocol):
    """One movement of credit, as the panel and the bot render it."""

    id: str
    amount: int
    balance_after: int
    kind: str
    description_fa: str
    reference: str | None
    occurred_at: datetime


class ResellerRepository(Protocol):
    """Storage for reseller accounts.

    `save` writes the aggregate whole - balance, discount, status, panels and
    overrides together - because they are read together and a partial write is
    how a reseller ends up priced for panels they cannot reach.
    """

    async def get(self, reseller_id: uuid.UUID) -> Reseller | None: ...

    async def get_by_admin(self, admin_id: uuid.UUID) -> Reseller | None:
        """The reseller behind a login.

        This is the whole of reseller authorisation: the token says which admin
        account is calling, and this says which rows are theirs.
        """
        ...

    async def list_all(self) -> Sequence[Reseller]: ...

    async def add(self, reseller: Reseller) -> None: ...

    async def save(self, reseller: Reseller) -> None: ...

    async def record(
        self,
        *,
        reseller_id: uuid.UUID,
        entry_id: str,
        amount: int,
        balance_after: int,
        kind: str,
        description_fa: str,
        occurred_at: datetime,
        reference: str | None = None,
        actor_id: int | None = None,
    ) -> None:
        """Append to the credit ledger. Never updates, never deletes."""
        ...

    async def history(
        self, reseller_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[LedgerEntry]: ...

    async def set_bot(
        self, reseller_id: uuid.UUID, *, token: str | None, username: str | None
    ) -> None:
        """Store or clear the reseller's own bot credential.

        Separate from `save` because a token is a secret with its own column
        and its own encryption context, and writing the aggregate must not be
        able to overwrite it by omission.
        """
        ...

    async def bot_token(self, reseller_id: uuid.UUID) -> str | None:
        """Decrypted, for the process that has to run the bot.

        Never reaches an API response. The panel shows `bot_username` and
        whether a token is set, which is everything an operator needs to know.
        """
        ...


class ResellerNames(Protocol):
    """The display names of many resellers at once.

    A list of subscriptions shows who sold each one, and asking per row is how
    a page of fifty becomes fifty queries.
    """

    async def names_for(
        self, reseller_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, str]: ...


class PlanPrices(Protocol):
    """List prices, so the service can quote a reseller without the catalogue.

    Narrow on purpose: reseller pricing needs a number per plan and nothing
    else about a plan, and depending on the whole storefront read model here
    would drag campaign and coupon logic into a credit calculation.
    """

    async def list_price(self, plan_id: uuid.UUID) -> Money | None: ...


__all__ = ["Clock", "LedgerEntry", "PlanPrices", "ResellerNames", "ResellerRepository"]
