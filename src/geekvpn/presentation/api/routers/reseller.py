"""What a reseller can do with their own account.

Every endpoint here resolves the caller to *their* reseller record first and
scopes everything to it. That is not a convention to remember - it is the only
way any of these read anything, because none of them accept a reseller id.
There is no path through this router that can be pointed at somebody else's
rows, which is the property a permission list cannot express.

A reseller signs in at the same endpoint as any operator and gets the same kind
of token; the role is what narrows them, and this is what narrows the rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ConfigDict, Field

from geekvpn.application.resellers.tenant_bots import InvalidBotToken
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.resellers.errors import (
    InsufficientCredit,
    ResellerNotFound,
    ResellerSuspended,
)
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep, requires
from geekvpn.presentation.bot.ui import copy as C

router = APIRouter(prefix="/reseller", tags=["reseller"])


class MeResponse(ApiModel):
    id: uuid.UUID
    name_fa: str
    #: What their bot calls itself. Falls back to `name_fa`, never to ours.
    brand_fa: str
    status: str
    balance: int
    discount_percent: int
    in_arrears: bool
    bot_username: str | None
    has_bot: bool


class PriceRow(ApiModel):
    plan_id: str
    name: str
    duration_days: int
    #: What anyone pays on the platform's own storefront. Shown so a reseller
    #: can see where their own price sits against it.
    list_price: int
    #: What this package costs them.
    cost: int
    #: What they have decided to charge. Defaults to the list price until they
    #: decide, so the number on their customer's screen is never blank.
    retail: int


class SubscriptionRow(ApiModel):
    id: str
    state: str
    remote_username: str
    subscription_url: str | None
    expires_at: datetime
    traffic_used_mib: int
    traffic_limit_mib: int | None


class LedgerRow(ApiModel):
    amount: int
    balance_after: int
    kind: str
    description_fa: str
    occurred_at: datetime


class SummaryResponse(ApiModel):
    sales: int
    spent: int
    topped_up: int
    average_sale: int


#: How many customers one broadcast reaches.
#:
#: A ceiling rather than paging, because this runs inside a request: a reseller
#: with more customers than this needs the platform's own broadcast machinery,
#: with its jobs and its retries, not a longer loop in an HTTP handler.
_BROADCAST_CAP = 500


class BroadcastRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    body_fa: str = Field(min_length=1, max_length=1000)


class BroadcastResult(ApiModel):
    sent: int
    failed: int
    total: int


class TextRow(ApiModel):
    key: str
    label_fa: str
    #: What the platform says. Shown beside theirs, because an edit is a
    #: comparison and a form that hides the default makes it blind.
    default_fa: str
    #: Their override, or None when they follow ours.
    body_fa: str | None
    #: Fields the text must keep, like `{brand}` or `{amount}`.
    placeholders: list[str]


class TextRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Empty restores the platform's wording rather than showing a blank
    #: screen: clearing a message means "use the normal one", never "say
    #: nothing".
    body_fa: str = Field(default="", max_length=2000)


class CustomerRow(ApiModel):
    id: uuid.UUID
    telegram_id: int
    username: str | None
    display_name: str
    status: str
    created_at: datetime


class CustomersResponse(ApiModel):
    total: int
    items: list[CustomerRow]


class TopupRow(ApiModel):
    id: uuid.UUID
    amount: int
    note_fa: str | None
    state: str
    created_at: datetime


class TopupRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0)
    #: Whatever identifies the transfer - a reference number, the last digits
    #: of the card it came from.
    note_fa: str = Field(default="", max_length=256)


class SaleResponse(ApiModel):
    subscription_id: str
    subscription_url: str | None
    remote_username: str
    expires_at: datetime
    charged: int
    balance_after: int


class SellRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    #: Whatever the reseller wants to remember this sale by - a customer's
    #: name, a phone number. It goes on their ledger line and nowhere else.
    note_fa: str = Field(default="", max_length=128)


class BrandRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    brand_fa: str = Field(default="", max_length=64)


class BotRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Goes in, never comes back. Telegram's own format is `<id>:<secret>`.
    token: str = Field(min_length=20, max_length=128)


class RetailRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    prices: dict[uuid.UUID, int] = Field(default_factory=dict)


async def _me(scope: Any, admin: Any) -> Any:
    """The caller's own reseller record, or 403.

    Not 404: the account exists and authenticated successfully. It simply is
    not a reseller, and telling it so is clearer than pretending the endpoint
    is missing.
    """
    try:
        return await scope.reseller_service.for_admin(admin.subject_id)
    except ResellerNotFound as failure:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This account is not a reseller."
        ) from failure


@router.get(
    "/me",
    response_model=MeResponse,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def me(scope: ScopeDep, admin: CurrentAdmin) -> MeResponse:
    reseller = await _me(scope, admin)
    # The token only to answer "is one configured"; it never leaves this
    # function. The username is what a person actually needs to see.
    token = await scope.resellers.bot_token(reseller.id)
    username = await scope.resellers.bot_username(reseller.id)
    return MeResponse(
        id=reseller.id,
        name_fa=reseller.name_fa,
        brand_fa=reseller.brand_fa or reseller.name_fa,
        status=reseller.status.value,
        balance=reseller.balance_amount,
        discount_percent=reseller.discount_percent,
        in_arrears=reseller.in_arrears,
        bot_username=username,
        has_bot=bool(token),
    )


@router.get(
    "/plans",
    response_model=list[PriceRow],
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def plans(scope: ScopeDep, admin: CurrentAdmin) -> list[PriceRow]:
    """Every package with all three numbers on it.

    List price, cost, and what they charge - on one screen, because a reseller
    choosing what to sell is comparing their margin, and making them hold two
    screens side by side is how they end up pricing from memory.
    """
    reseller = await _me(scope, admin)
    rows = await scope.reseller_sales.price_list(
        reseller.id, await scope.catalog_plans.list_all(published_only=True)
    )
    return [PriceRow(**row) for row in rows]


@router.put(
    "/plans/retail",
    response_model=list[PriceRow],
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def set_retail(
    payload: RetailRequest, scope: ScopeDep, admin: CurrentAdmin
) -> list[PriceRow]:
    """What this reseller charges their own customers. Theirs to decide."""
    reseller = await _me(scope, admin)
    await scope.reseller_service.set_retail(reseller.id, payload.prices)
    rows = await scope.reseller_sales.price_list(
        reseller.id, await scope.catalog_plans.list_all(published_only=True)
    )
    return [PriceRow(**row) for row in rows]


@router.put(
    "/brand",
    response_model=MeResponse,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def set_brand(
    payload: BrandRequest, scope: ScopeDep, admin: CurrentAdmin
) -> MeResponse:
    """What their bot calls itself.

    Theirs to choose. Until they do it falls back to the name we file them
    under, which is still their name - never ours.
    """
    reseller = await _me(scope, admin)
    await scope.reseller_service.update(reseller.id, brand_fa=payload.brand_fa)
    return await me(scope, admin)


@router.put(
    "/bot",
    response_model=MeResponse,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def attach_bot(
    payload: BotRequest, scope: ScopeDep, admin: CurrentAdmin
) -> MeResponse:
    """Point a reseller's own Telegram bot at this platform.

    Here rather than only in the operator's screen, because it is their bot and
    their token - and an operator who has to be asked to paste somebody else's
    credential is an operator who now has it.

    In the panel and not in the chat, for the same reason: a token typed into
    Telegram is a full credential in somebody's message history forever.
    """
    reseller = await _me(scope, admin)
    telegram = scope.container.settings.telegram
    try:
        await scope.reseller_service.attach_bot(
            reseller.id,
            token=payload.token,
            webhook_base_url=telegram.webhook_base_url,
            webhook_path=telegram.webhook_path,
            platform_secret=telegram.webhook_secret.get_secret_value(),
        )
    except InvalidBotToken as failure:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(failure)) from failure
    return await me(scope, admin)


@router.delete(
    "/bot",
    response_model=MeResponse,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def detach_bot(scope: ScopeDep, admin: CurrentAdmin) -> MeResponse:
    reseller = await _me(scope, admin)
    try:
        await scope.reseller_service.detach_bot(reseller.id)
    except InvalidBotToken as failure:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(failure)) from failure
    return await me(scope, admin)


@router.post(
    "/topups",
    response_model=list[TopupRow],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def request_topup(
    payload: TopupRequest, scope: ScopeDep, admin: CurrentAdmin
) -> list[TopupRow]:
    """Ask for credit. An operator decides whether the money arrived.

    No gateway here on purpose. A reseller transfers to the platform however
    the two of them already arrange it, and inventing a second payment system
    for a handful of people would be a second place for money to go missing.
    """
    reseller = await _me(scope, admin)
    try:
        await scope.reseller_topups.request(
            reseller_id=reseller.id, amount=payload.amount, note_fa=payload.note_fa
        )
    except ValueError as failure:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(failure)) from failure
    return await my_topups(scope, admin)


@router.get(
    "/topups",
    response_model=list[TopupRow],
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def my_topups(scope: ScopeDep, admin: CurrentAdmin) -> list[TopupRow]:
    reseller = await _me(scope, admin)
    return [
        TopupRow(
            id=row.id,
            amount=row.amount,
            note_fa=row.note_fa,
            state=row.state,
            created_at=row.created_at,
        )
        for row in await scope.reseller_topups.mine(reseller.id)
    ]


@router.get(
    "/subscriptions",
    response_model=list[SubscriptionRow],
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def subscriptions(scope: ScopeDep, admin: CurrentAdmin) -> list[SubscriptionRow]:
    reseller = await _me(scope, admin)
    rows = await scope.subscriptions.list_for_reseller(reseller.id)
    return [
        SubscriptionRow(
            id=row.id,
            state=row.state.value,
            remote_username=row.remote_username,
            subscription_url=row.subscription_url,
            expires_at=row.expires_at,
            traffic_used_mib=row.traffic_used_mib,
            traffic_limit_mib=row.traffic_limit_mib,
        )
        for row in rows
    ]


@router.get(
    "/summary",
    response_model=SummaryResponse,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def summary(scope: ScopeDep, admin: CurrentAdmin) -> SummaryResponse:
    """Four numbers about their own trade, off their own ledger.

    Not the platform's analytics service. That one is scoped to nothing, and
    pointing a reseller at it would be a second door into everyone's figures
    for a screen that needs four sums.
    """
    reseller = await _me(scope, admin)
    numbers = await scope.reseller_service.summary(reseller.id)
    return SummaryResponse(**numbers)


@router.post(
    "/broadcast",
    response_model=BroadcastResult,
    dependencies=[Depends(requires(Permission.RESELLER_SELL))],
)
async def broadcast(
    payload: BroadcastRequest, scope: ScopeDep, admin: CurrentAdmin
) -> BroadcastResult:
    """One message to this reseller's own customers.

    Sent through *their* bot. A message from ours would be refused outright -
    Telegram will not let a bot open a conversation the person never started -
    and refused deliveries are recorded as suppressions, so it would look like
    every one of their customers had blocked them.

    Their customers, by construction: the audience is read from the shop, and
    this endpoint takes no shop id to point elsewhere.
    """
    reseller = await _me(scope, admin)
    rows, _ = await scope.users.list_for_reseller(reseller.id, limit=_BROADCAST_CAP)

    sent = 0
    failed = 0
    for row in rows:
        try:
            await scope.notify_customer(row.telegram_id, payload.body_fa)
            sent += 1
        except Exception:
            # One unreachable person must not stop the other four hundred.
            # Somebody who blocked the bot is the usual cause and is not an
            # error worth failing a broadcast over.
            failed += 1
    return BroadcastResult(sent=sent, failed=failed, total=len(rows))


@router.get(
    "/texts",
    response_model=list[TextRow],
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def texts(scope: ScopeDep, admin: CurrentAdmin) -> list[TextRow]:
    """Every screen a reseller may rewrite, with theirs and ours side by side.

    Both, because an edit is a comparison: a reseller changing the welcome is
    deciding whether their words beat the ones already there, and a form that
    hides the default makes that decision blind.
    """
    reseller = await _me(scope, admin)
    overrides = await scope.resellers.texts(reseller.id)
    return [
        TextRow(
            key=key,
            label_fa=label,
            default_fa=C.default_for(key),
            body_fa=overrides.get(key),
            placeholders=list(C.placeholders(key)),
        )
        for key, label in C.EDITABLE.items()
    ]


@router.put(
    "/texts/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def set_text(
    key: str, payload: TextRequest, scope: ScopeDep, admin: CurrentAdmin
) -> None:
    """Rewrite one screen, or empty it to go back to ours."""
    if key not in C.EDITABLE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such screen.")

    body = payload.body_fa.strip()
    if body:
        missing = [
            field for field in C.placeholders(key) if "{" + field + "}" not in body
        ]
        if missing:
            # Refused rather than accepted and discovered later. A welcome
            # without `{brand}` is the reseller's business; a payment screen
            # without `{amount}` is a customer who does not know what to send.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "این متن باید شامل " + "، ".join("{" + f + "}" for f in missing) + " باشد.",
            )

    reseller = await _me(scope, admin)
    await scope.resellers.set_text(reseller.id, key=key, body_fa=body)


@router.get(
    "/customers",
    response_model=CustomersResponse,
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def customers(
    scope: ScopeDep,
    admin: CurrentAdmin,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> CustomersResponse:
    """The people who have used this reseller's bot.

    Their own, by construction: a customer belongs to a shop, and this cannot
    be pointed at another one because it never takes a shop id.
    """
    reseller = await _me(scope, admin)
    rows, total = await scope.users.list_for_reseller(
        reseller.id, limit=limit, offset=offset
    )
    return CustomersResponse(
        total=total,
        items=[
            CustomerRow(
                id=row.id,
                telegram_id=row.telegram_id,
                username=row.username,
                display_name=row.display_name,
                status=row.status.value,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.get(
    "/ledger",
    response_model=list[LedgerRow],
    dependencies=[Depends(requires(Permission.RESELLER_PORTAL))],
)
async def ledger(
    scope: ScopeDep,
    admin: CurrentAdmin,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> list[LedgerRow]:
    reseller = await _me(scope, admin)
    entries = await scope.reseller_service.history(reseller.id, limit=limit)
    return [
        LedgerRow(
            amount=entry.amount,
            balance_after=entry.balance_after,
            kind=entry.kind,
            description_fa=entry.description_fa,
            occurred_at=entry.occurred_at,
        )
        for entry in entries
    ]


@router.post(
    "/sell",
    response_model=SaleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires(Permission.RESELLER_SELL))],
)
async def sell(
    payload: SellRequest, scope: ScopeDep, admin: CurrentAdmin
) -> SaleResponse:
    """Create one service, paid for out of the reseller's credit."""
    reseller = await _me(scope, admin)
    try:
        sale = await scope.reseller_sales.sell(
            reseller_id=reseller.id, plan_id=payload.plan_id, note_fa=payload.note_fa
        )
    except InsufficientCredit as failure:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"Top up by at least {failure.shortfall} Toman.",
        ) from failure
    except ResellerSuspended as failure:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(failure)) from failure
    except LookupError as failure:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such package.") from failure

    return SaleResponse(
        subscription_id=sale.subscription_id,
        subscription_url=sale.subscription_url,
        remote_username=sale.remote_username,
        expires_at=sale.expires_at,
        charged=sale.charged.amount,
        balance_after=sale.balance_after,
    )
