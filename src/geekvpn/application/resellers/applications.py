"""Somebody asking to sell under their own name, and what approval produces.

An application is not a request for permission that gets a yes and stops. Yes
has to leave a working reseller behind: a record with prices and panels, a
login, a way into the bot, and a way into the panel that does not involve a
password travelling through Telegram.

So `approve` does four things at once, and the alternative - a yes that only
flips a flag, followed by an operator remembering to create the reseller - is
how a person ends up approved and unable to sell anything.
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from geekvpn.application.resellers.ports import Clock
from geekvpn.application.resellers.service import ResellerService
from geekvpn.domain.resellers.reseller import Reseller

#: How long a "set your password" link is good for.
#:
#: A day, not an hour: it arrives in a chat somebody may not be looking at, and
#: a link that expired while they slept is a support conversation. Not a week
#: either - it is a credential, and one nobody has used in a day is one that
#: was probably sent to the wrong person.
SETUP_TOKEN_TTL = timedelta(days=1)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


class AlreadyApplied(Exception):
    """One pending application per person.

    The database enforces it too, with a partial unique index. This exists so
    the bot can say something useful instead of showing a constraint violation.
    """


class ApplicationNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ApplicationView:
    id: uuid.UUID
    telegram_id: int
    name_fa: str
    contact_fa: str | None
    note_fa: str | None
    state: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Approval:
    """What an approval produced, so the bot can tell the applicant."""

    reseller: Reseller
    username: str
    #: The one-time secret for the "set your password" link. Returned once and
    #: stored only as a hash - this is the single moment it exists in the open.
    setup_token: str


class ApplicationRepository(Protocol):
    async def add(self, **fields: Any) -> uuid.UUID: ...

    async def pending_for(self, telegram_id: int) -> ApplicationView | None: ...

    async def get(self, application_id: uuid.UUID) -> ApplicationView | None: ...

    async def list_pending(self, *, limit: int = 50) -> Sequence[ApplicationView]: ...

    async def decide(
        self,
        application_id: uuid.UUID,
        *,
        state: str,
        decided_by: int | None,
        decided_at: datetime,
        reason_fa: str | None = None,
        reseller_id: uuid.UUID | None = None,
    ) -> None: ...


class SetupTokens(Protocol):
    """Stores the hash of a one-time password-setup secret on an admin."""

    async def issue(
        self, admin_id: uuid.UUID, *, token_hash: str, expires_at: datetime
    ) -> None: ...


class ResellerApplications:
    def __init__(
        self,
        *,
        applications: ApplicationRepository,
        resellers: ResellerService,
        setup_tokens: SetupTokens,
        hasher: Any,
        clock: Clock,
    ) -> None:
        self._applications = applications
        self._resellers = resellers
        self._setup_tokens = setup_tokens
        self._hasher = hasher
        self._clock = clock

    async def apply(
        self,
        *,
        telegram_id: int,
        name_fa: str,
        contact_fa: str | None = None,
        note_fa: str | None = None,
    ) -> uuid.UUID:
        if await self._applications.pending_for(telegram_id) is not None:
            raise AlreadyApplied("There is already an application waiting.")
        return await self._applications.add(
            id=uuid.uuid4(),
            telegram_id=telegram_id,
            name_fa=name_fa.strip(),
            contact_fa=(contact_fa or "").strip() or None,
            note_fa=(note_fa or "").strip() or None,
            state=PENDING,
        )

    async def pending(self, *, limit: int = 50) -> Sequence[ApplicationView]:
        return await self._applications.list_pending(limit=limit)

    async def status_for(self, telegram_id: int) -> ApplicationView | None:
        return await self._applications.pending_for(telegram_id)

    async def approve(
        self,
        application_id: uuid.UUID,
        *,
        discount_percent: int = 0,
        decided_by: int | None = None,
    ) -> Approval:
        """Say yes, and leave a reseller who can actually sell.

        Four things together, because any three of them is a person who has
        been told yes and cannot do anything: the reseller record, the login,
        the Telegram id that gets them into the bot, and a one-time link that
        lets them choose a panel password nobody had to send them.
        """
        application = await self._applications.get(application_id)
        if application is None or application.state != PENDING:
            raise ApplicationNotFound("No such application is waiting.")

        created = await self._resellers.create(
            username=_username_from(application),
            name_fa=application.name_fa,
            discount_percent=discount_percent,
            contact_fa=application.contact_fa,
            telegram_id=application.telegram_id,
        )

        # Long enough that guessing is pointless, and it never appears in a
        # log: only its hash is stored, and only the link carries the value.
        token = secrets.token_urlsafe(32)
        await self._setup_tokens.issue(
            created.reseller.admin_id,
            token_hash=self._hasher.hash(token),
            expires_at=self._clock.now() + SETUP_TOKEN_TTL,
        )

        await self._applications.decide(
            application_id,
            state=APPROVED,
            decided_by=decided_by,
            decided_at=self._clock.now(),
            reseller_id=created.reseller.id,
        )
        return Approval(
            reseller=created.reseller, username=created.username, setup_token=token
        )

    async def reject(
        self,
        application_id: uuid.UUID,
        *,
        reason_fa: str = "",
        decided_by: int | None = None,
    ) -> ApplicationView:
        application = await self._applications.get(application_id)
        if application is None or application.state != PENDING:
            raise ApplicationNotFound("No such application is waiting.")
        await self._applications.decide(
            application_id,
            state=REJECTED,
            decided_by=decided_by,
            decided_at=self._clock.now(),
            reason_fa=reason_fa.strip() or None,
        )
        return application


def _username_from(application: ApplicationView) -> str:
    """A login name derived from the application, not chosen by the applicant.

    Their Telegram id is in it because it is the one thing guaranteed unique -
    a shop called "gib" is not, and two of them would collide on the second
    approval, in a flow where the operator has no field to fix it in.
    """
    stem = re.sub(r"[^a-z0-9]+", "", application.name_fa.lower())[:16]
    return f"{stem or 'reseller'}{application.telegram_id}"


__all__ = [
    "APPROVED",
    "PENDING",
    "REJECTED",
    "SETUP_TOKEN_TTL",
    "AlreadyApplied",
    "ApplicationNotFound",
    "ApplicationRepository",
    "ApplicationView",
    "Approval",
    "ResellerApplications",
    "SetupTokens",
]
