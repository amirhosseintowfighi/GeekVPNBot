"""Reseller administration.

Everything an operator does to a reseller: create them with a login, set their
discount, price individual packages by hand, choose which panels they may sell
from, move their credit, and read where that credit went.

Two things never come back out of here:

* the login password, which is generated on creation, returned in that one
  response and never stored in readable form;
* the reseller's bot token, which is a full credential. Responses carry
  ``has_bot`` and the bot's public @username, which is everything an operator
  needs in order to know whether it is configured.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ConfigDict, Field

from geekvpn.application.resellers.tenant_bots import InvalidBotToken
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.domain.resellers.errors import ResellerNotFound
from geekvpn.domain.resellers.reseller import MAX_DISCOUNT_PERCENT, Reseller
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep, requires

router = APIRouter(prefix="/admin/resellers", tags=["administration"])


class ResellerResponse(ApiModel):
    id: uuid.UUID
    admin_id: uuid.UUID
    name_fa: str
    status: ResellerStatus
    discount_percent: int
    balance: int
    contact_fa: str | None
    allowed_node_ids: list[str]
    #: Plan id to the price this reseller pays, where a percentage was the
    #: wrong shape and an operator typed a number instead.
    costs: dict[str, int]
    #: Plan id to what this reseller charges their own customers. Theirs, not
    #: ours - absent means they have not decided and the list price stands.
    retail: dict[str, int]
    #: Whether their own Telegram bot is configured. Never the token itself.
    has_bot: bool = False
    bot_username: str | None = None
    #: A reseller whose balance has gone under. Their customers' services are
    #: suspended until it is positive again.
    in_arrears: bool = False

    @classmethod
    def of(cls, reseller: Reseller, *, bot_username: str | None = None) -> ResellerResponse:
        return cls(
            bot_username=bot_username,
            has_bot=bool(bot_username),
            id=reseller.id,
            admin_id=reseller.admin_id,
            name_fa=reseller.name_fa,
            status=reseller.status,
            discount_percent=reseller.discount_percent,
            balance=reseller.balance_amount,
            contact_fa=reseller.contact_fa,
            allowed_node_ids=sorted(reseller.allowed_node_ids),
            costs={
                str(override.plan_id): override.cost.amount
                for override in reseller.overrides
                if override.cost is not None
            },
            retail={
                str(override.plan_id): override.retail.amount
                for override in reseller.overrides
                if override.retail is not None
            },
            in_arrears=reseller.in_arrears,
        )


class CreatedResellerResponse(ApiModel):
    """The only time the password exists anywhere readable.

    An operator who closes this dialog without copying it resets the account
    rather than recovering the value, which is the point of hashing it.
    """

    reseller: ResellerResponse
    username: str
    password: str


class LedgerEntryResponse(ApiModel):
    id: str
    amount: int
    balance_after: int
    kind: str
    description_fa: str
    reference: str | None
    occurred_at: datetime


class PriceRow(ApiModel):
    plan_id: str
    name: str
    duration_days: int
    #: What anyone pays on the storefront.
    list_price: int
    #: What this reseller pays.
    cost: int
    #: What this reseller charges their own customer.
    retail: int


class BotRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Goes in, never comes back. Telegram's own format is `<id>:<secret>`.
    token: str = Field(min_length=20, max_length=128)


class BotResponse(ApiModel):
    bot_username: str | None
    has_bot: bool


class CreateResellerRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    name_fa: str = Field(min_length=1, max_length=128)
    discount_percent: int = Field(default=0, ge=0, le=MAX_DISCOUNT_PERCENT)
    contact_fa: str | None = Field(default=None, max_length=256)


class UpdateResellerRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    name_fa: str | None = Field(default=None, min_length=1, max_length=128)
    status: ResellerStatus | None = None
    discount_percent: int | None = Field(default=None, ge=0, le=MAX_DISCOUNT_PERCENT)
    contact_fa: str | None = Field(default=None, max_length=256)


class PanelsRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Empty means every panel. An operator who has not restricted anything has
    #: not yet made a decision, and refusing to provision would be a strange
    #: reading of that.
    node_ids: list[str] = Field(default_factory=list)


class PricesRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Plan id to price in Toman. Sent whole within its own half: the map
    #: replaces what was there, so removing a price is sending the map without
    #: it. The other half - cost or retail - is left alone, because the two are
    #: set by two different people and neither may erase the other.
    prices: dict[uuid.UUID, int] = Field(default_factory=dict)


class CreditRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Signed. Negative deducts, and may take the balance below zero - a
    #: settlement, a disputed charge, a correction. A reseller in arrears has
    #: their customers' services suspended until it is positive again, which is
    #: how the credit limit is enforced.
    amount: int
    description_fa: str = Field(min_length=1, max_length=256)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "No such reseller.")


@router.get(
    "",
    response_model=list[ResellerResponse],
    dependencies=[Depends(requires(Permission.RESELLERS_READ))],
)
async def list_resellers(scope: ScopeDep) -> list[ResellerResponse]:
    rows = await scope.reseller_service.list_all()
    # One query per reseller for the bot's public name. A join would be tidier
    # and this list is a handful of rows on a screen an operator opens rarely -
    # the tidier version is worth writing when it is worth measuring.
    return [
        ResellerResponse.of(
            reseller,
            bot_username=await scope.resellers.bot_username(reseller.id),
        )
        for reseller in rows
    ]


@router.get(
    "/{reseller_id}",
    response_model=ResellerResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_READ))],
)
async def get_reseller(reseller_id: uuid.UUID, scope: ScopeDep) -> ResellerResponse:
    try:
        return ResellerResponse.of(await scope.reseller_service.get(reseller_id))
    except ResellerNotFound as failure:
        raise _not_found() from failure


@router.post(
    "",
    response_model=CreatedResellerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def create_reseller(
    payload: CreateResellerRequest, scope: ScopeDep, admin: CurrentAdmin
) -> CreatedResellerResponse:
    created = await scope.reseller_service.create(
        username=payload.username,
        name_fa=payload.name_fa,
        discount_percent=payload.discount_percent,
        contact_fa=payload.contact_fa,
        actor_id=admin.subject_id,
    )
    return CreatedResellerResponse(
        reseller=ResellerResponse.of(created.reseller),
        username=created.username,
        password=created.password,
    )


@router.patch(
    "/{reseller_id}",
    response_model=ResellerResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def update_reseller(
    reseller_id: uuid.UUID, payload: UpdateResellerRequest, scope: ScopeDep
) -> ResellerResponse:
    try:
        reseller = await scope.reseller_service.update(
            reseller_id,
            name_fa=payload.name_fa,
            status=payload.status,
            discount_percent=payload.discount_percent,
            contact_fa=payload.contact_fa,
        )
    except ResellerNotFound as failure:
        raise _not_found() from failure
    return ResellerResponse.of(reseller)


@router.put(
    "/{reseller_id}/panels",
    response_model=ResellerResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def set_panels(
    reseller_id: uuid.UUID, payload: PanelsRequest, scope: ScopeDep
) -> ResellerResponse:
    known = {node.id for node in await scope.nodes.list_all()}
    unknown = sorted(set(payload.node_ids) - known)
    if unknown:
        # Refused rather than stored: a reseller allowed onto a panel that does
        # not exist is a restriction that silently does nothing.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Unknown panels: {', '.join(unknown)}"
        )
    try:
        reseller = await scope.reseller_service.set_panels(reseller_id, payload.node_ids)
    except ResellerNotFound as failure:
        raise _not_found() from failure
    return ResellerResponse.of(reseller)


@router.put(
    "/{reseller_id}/costs",
    response_model=ResellerResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def set_costs(
    reseller_id: uuid.UUID, payload: PricesRequest, scope: ScopeDep
) -> ResellerResponse:
    """What the platform charges this reseller. An operator's decision."""
    try:
        reseller = await scope.reseller_service.set_costs(reseller_id, payload.prices)
    except ResellerNotFound as failure:
        raise _not_found() from failure
    return ResellerResponse.of(reseller)


@router.put(
    "/{reseller_id}/retail",
    response_model=ResellerResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def set_retail(
    reseller_id: uuid.UUID, payload: PricesRequest, scope: ScopeDep
) -> ResellerResponse:
    """What this reseller charges their own customers.

    Reachable by an operator as well as by the reseller, because the first
    thing a reseller asks support is to set their prices for them while they
    work out the panel.
    """
    try:
        reseller = await scope.reseller_service.set_retail(reseller_id, payload.prices)
    except ResellerNotFound as failure:
        raise _not_found() from failure
    return ResellerResponse.of(reseller)


@router.put(
    "/{reseller_id}/bot",
    response_model=BotResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def attach_bot(
    reseller_id: uuid.UUID, payload: BotRequest, scope: ScopeDep
) -> BotResponse:
    """Give a reseller their own Telegram bot.

    The token goes in and never comes back out. It is a full credential - one
    leaked from a response lets somebody impersonate the reseller to every one
    of their customers - so it is stored encrypted and answered for with a
    @username and a boolean.

    Telegram is asked to identify the token before it is stored, and pointed at
    this platform after. A token nobody verified is a bot that will silently
    receive nothing.
    """
    telegram = scope.container.settings.telegram
    try:
        username = await scope.reseller_service.attach_bot(
            reseller_id,
            token=payload.token,
            webhook_base_url=telegram.webhook_base_url,
            webhook_path=telegram.webhook_path,
            platform_secret=telegram.webhook_secret.get_secret_value(),
        )
    except ResellerNotFound as failure:
        raise _not_found() from failure
    except InvalidBotToken as failure:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(failure)) from failure
    return BotResponse(bot_username=username, has_bot=True)


@router.delete(
    "/{reseller_id}/bot",
    response_model=BotResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def detach_bot(reseller_id: uuid.UUID, scope: ScopeDep) -> BotResponse:
    try:
        await scope.reseller_service.detach_bot(reseller_id)
    except ResellerNotFound as failure:
        raise _not_found() from failure
    except InvalidBotToken as failure:
        # Telegram refused to drop the webhook. The token is cleared either
        # way by the service, so this is worth reporting and not worth failing.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(failure)) from failure
    return BotResponse(bot_username=None, has_bot=False)


@router.get(
    "/{reseller_id}/prices",
    response_model=list[PriceRow],
    dependencies=[Depends(requires(Permission.RESELLERS_READ))],
)
async def price_list(reseller_id: uuid.UUID, scope: ScopeDep) -> list[PriceRow]:
    """Every package with all three numbers on it, for one reseller.

    One request rather than a product list followed by a plan list per product:
    this is a drawer that opens on a click, and an operator comparing a
    reseller's margin should not watch a dozen round trips resolve.
    """
    rows = await scope.reseller_sales.price_list(
        reseller_id, await scope.catalog_plans.list_all(published_only=True)
    )
    return [PriceRow(**row) for row in rows]


@router.post(
    "/{reseller_id}/credit",
    response_model=ResellerResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def adjust_credit(
    reseller_id: uuid.UUID,
    payload: CreditRequest,
    scope: ScopeDep,
    admin: CurrentAdmin,
) -> ResellerResponse:
    try:
        reseller = await scope.reseller_service.adjust_credit(
            reseller_id,
            amount=payload.amount,
            description_fa=payload.description_fa,
            # The audit trail wants a Telegram id here, which an operator has
            # only if they linked one. None is the honest answer otherwise.
            actor_id=None,
        )
    except ResellerNotFound as failure:
        raise _not_found() from failure
    return ResellerResponse.of(reseller)


@router.get(
    "/{reseller_id}/ledger",
    response_model=list[LedgerEntryResponse],
    dependencies=[Depends(requires(Permission.RESELLERS_READ))],
)
async def read_ledger(
    reseller_id: uuid.UUID,
    scope: ScopeDep,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> list[LedgerEntryResponse]:
    entries = await scope.reseller_service.history(reseller_id, limit=limit)
    return [
        LedgerEntryResponse(
            id=entry.id,
            amount=entry.amount,
            balance_after=entry.balance_after,
            kind=entry.kind,
            description_fa=entry.description_fa,
            reference=entry.reference,
            occurred_at=entry.occurred_at,
        )
        for entry in entries
    ]
