"""The Mini App's backend.

Sixteen endpoints the front-end had been calling against nothing. They are thin
by design: every one of them delegates to the same ``BotServices`` bundle the
Telegram bot uses, so the two front-ends cannot drift apart on what a
subscription or a wallet balance means. There is no service layer here, because
adding one would be a second place for that meaning to live.

The prefix is ``/api/miniapp`` rather than ``/api/v1/miniapp``: that is what the
front-end already calls, and it is checked by
``tests/integration/test_miniapp_api_contract.py``.
"""

from __future__ import annotations

import dataclasses
import functools
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.datastructures import DefaultPlaceholder
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from geekvpn.application.bot.read_models import NotificationPreferences
from geekvpn.application.payments.receipt_intent import (
    RECEIPT_INTENT_TTL_SECONDS,
    RECEIPT_REQUESTED_TEMPLATE,
    receipt_intent_key,
)
from geekvpn.application.support.ticket_service import MessageView, ReplyRequest
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.payments.enums import PaymentMethod, PaymentState
from geekvpn.domain.payments.payment import Payment
from geekvpn.infrastructure.bot.checkout import CARD, REVIEW_SLA_FA, payment_uuid
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import mutate_scope, read_scope
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep, UnitOfWorkDep
from geekvpn.presentation.api.miniapp_security import CurrentMiniAppUser, ServicesDep
from geekvpn.presentation.api.security import ScopeDep


#: The Mini App reads camelCase everywhere. Endpoints with a response model
#: get that from ``ApiModel``; the ones that hand back an application read
#: model directly used to emit its Python field names instead, so the front
#: end read ``usedGib`` off a payload that said ``used_gib`` and rendered NaN.
class _CamelCaseRoute(APIRoute):
    """Serialises snake_case field names as camelCase.

    The alternative was a response model per endpoint - twenty schemas that
    restate the read models field for field, and drift from them silently the
    first time a field is added. The read models are already flat DTOs shaped
    for exactly these screens; the only thing wrong with them on the wire was
    the spelling.

    Routes that *do* declare a response model are left alone: ``ApiModel``
    already emits aliases, and camelising a name with no underscore in it is a
    no-op anyway.
    """

    def __init__(self, path: str, endpoint: Any, **kwargs: Any) -> None:
        model = kwargs.get("response_model")
        if isinstance(model, DefaultPlaceholder):
            model = model.value
        if model is None:
            endpoint = _camel_cased(endpoint)
        super().__init__(path, endpoint, **kwargs)


def _camel_cased(endpoint: Any) -> Any:
    @functools.wraps(endpoint)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _camelize(jsonable_encoder(await endpoint(*args, **kwargs)))

    return wrapper


def _camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {to_camel(key): _camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


router = APIRouter(prefix="/api/miniapp", tags=["mini-app"], route_class=_CamelCaseRoute)

#: A customer with more outstanding payments than this has a support problem,
#: not a pagination problem.
_PENDING_LIMIT = 50


def _require_own_ticket(scope: SyncScope, ticket_id: str, telegram_id: int) -> None:
    """Refuse a ticket that belongs to somebody else.

    The support service is written for agents, who may read any ticket, so the
    ownership check has to happen here. Answering 404 rather than 403 keeps a
    customer from confirming that a ticket id exists.
    """
    try:
        summary = scope.support.get_ticket(ticket_id)
    except DomainError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.") from exc
    if summary.user_id != telegram_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.")


def _message_view(message: MessageView) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "ticket_id": message.ticket_id,
        "kind": message.kind.value,
        # The Mini App draws two sides of a conversation and reads a boolean.
        # It was never sent one, so every message rendered as the customer's -
        # including the answers.
        "from_support": message.kind.value == "support",
        "body_fa": message.body_fa,
        "created_at": message.created_at,
        "attachment_count": message.attachment_count,
        "is_read": message.is_read,
    }


def _payment_view(payment: Payment, scope: SyncScope) -> dict[str, Any]:
    """The receipt digest stays server-side. The destination card does not.

    This is the screen a customer reads the card number off before making
    the transfer. Sending the payment without it left them on a page asking
    for a receipt for a transfer they were never told how to make.

    The card is registry configuration rather than something stored on the
    payment, which is deliberate: cards rotate, and a customer who is still
    mid-transfer should be shown the card that is active now.
    """
    card = (
        scope.gateways.get(CARD)
        if payment.method is PaymentMethod.CARD and scope.gateways.has(CARD)
        else None
    )
    return {
        # The same spelling `/checkout/card` returns, because the Mini App
        # navigates with that one and looks the payment up in this list.
        "payment_id": payment_uuid(payment.id),
        "reference": payment.id,
        "amount": payment.amount.amount,
        "method": payment.method.value,
        "state": payment.state.value,
        "created_at": payment.created_at,
        "expires_at": payment.expires_at,
        "card": (
            {
                "card_number": getattr(card, "card_number", ""),
                "card_holder_fa": getattr(card, "card_holder_fa", ""),
                "bank_fa": getattr(card, "bank_name_fa", ""),
                "review_sla_fa": REVIEW_SLA_FA,
            }
            if card is not None
            else None
        ),
        # No crypto gateway is registered anywhere in the container, so a
        # crypto payment cannot exist to describe. Null is the honest answer
        # rather than an empty address the customer would send funds to.
        "crypto": None,
    }


# -- request bodies --------------------------------------------------------


class PlanRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    coupon_code: str | None = Field(default=None, max_length=64)


class CouponPreviewRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    code: str = Field(min_length=1, max_length=64)


class TopupRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0)
    method: str = Field(pattern="^(card|crypto)$")


class ReceiptRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=512)


class TxidRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    txid: str = Field(min_length=8, max_length=256)


class OpenTicketRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=128)
    subject: str = Field(default="", max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class TicketReplyRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class ProfileRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=64)


class PreferencesRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    expiry: bool = True
    traffic: bool = True
    promos: bool = True
    news: bool = True
    quiet_hours: bool = True


# -- storefront and pricing ------------------------------------------------


class PlanCard(ApiModel):
    """One purchasable package, as the Mini App renders it."""

    plan_id: uuid.UUID
    product_id: uuid.UUID
    name_fa: str
    plan_type: str
    duration_days: int
    price: int
    #: Struck through in the UI, so it is only sent where a real discount
    #: exists. Equal to the price would draw a line through the same number.
    compare_at_price: int | None
    quota_gib: int | None
    daily_quota_gib: int | None
    device_limit: int
    badge_fa: str | None
    is_featured: bool
    description_fa: str | None


class ProductCard(ApiModel):
    product_id: uuid.UUID
    category_id: uuid.UUID
    name_fa: str
    tagline_fa: str | None
    description_fa: str | None
    features_fa: list[str]
    icon: str | None
    badge_fa: str | None
    is_featured: bool
    plans: list[PlanCard]


class CategoryCard(ApiModel):
    category_id: uuid.UUID
    name_fa: str
    icon: str | None
    products: list[ProductCard]


class StorefrontResponse(ApiModel):
    categories: list[CategoryCard]
    wallet_balance: int
    loyalty_tier: str
    #: Whether a first-purchase-only offer applies to this customer. Not on the
    #: storefront view - it is a fact about the person, not the catalogue.
    is_first_purchase: bool


@router.get(
    "/storefront",
    response_model=StorefrontResponse,
    summary="Categories, products and priced plans",
)
async def storefront(user: CurrentMiniAppUser, scope: ScopeDep) -> StorefrontResponse:
    """The catalogue, in the shape the Mini App reads.

    This used to return the internal `StorefrontView` dataclass directly, typed
    `Any`. FastAPI serialised it field for field, so the payload arrived in
    snake_case with the domain's own names - `id`, `name`, `tagline` - while
    the Mini App reads `categoryId`, `nameFa`, `taglineFa`. Every one of them
    was undefined, mapping over `products` threw, and the whole storefront
    rendered as "a client-side exception has occurred".

    A response model rather than a hand-built dict: `ApiModel` emits camelCase
    from these names, and the shape is then something a schema can be checked
    against instead of a dictionary nobody validates.
    """
    view = await scope.storefront.load(user_id=user.id)
    first_purchase = not await scope.orders.has_completed_order(user.telegram_id)

    return StorefrontResponse(
        categories=[
            CategoryCard(
                category_id=category.id,
                name_fa=category.name,
                icon=category.icon,
                products=[
                    ProductCard(
                        product_id=product.id,
                        category_id=category.id,
                        name_fa=product.name,
                        tagline_fa=product.tagline,
                        description_fa=product.description,
                        features_fa=list(product.features),
                        icon=product.icon,
                        badge_fa=product.badge,
                        is_featured=product.is_featured,
                        plans=[
                            PlanCard(
                                plan_id=plan.id,
                                product_id=product.id,
                                name_fa=plan.name,
                                plan_type=plan.plan_type,
                                duration_days=plan.duration_days,
                                price=plan.price.total,
                                compare_at_price=(
                                    plan.price.compare_at_price
                                    if plan.price.compare_at_price
                                    and plan.price.compare_at_price > plan.price.total
                                    else None
                                ),
                                quota_gib=plan.quota_gib,
                                daily_quota_gib=plan.daily_quota_gib,
                                device_limit=plan.device_limit,
                                badge_fa=plan.badge,
                                is_featured=plan.is_featured,
                                description_fa=plan.description,
                            )
                            for plan in product.plans
                        ],
                    )
                    for product in category.products
                ],
            )
            for category in view.categories
        ],
        wallet_balance=view.wallet_balance,
        loyalty_tier=view.loyalty_tier,
        is_first_purchase=first_purchase,
    )


@router.post("/quote", summary="Price one plan for this customer")
async def quote(payload: PlanRequest, user: CurrentMiniAppUser, scope: ScopeDep) -> Any:
    return await scope.quoting.quote_view(
        plan_id=payload.plan_id, user_id=user.id, coupon_code=payload.coupon_code
    )


@router.post("/coupon/preview", summary="Check a coupon before checkout")
async def preview_coupon(
    payload: CouponPreviewRequest, user: CurrentMiniAppUser, scope: ScopeDep
) -> Any:
    return await scope.quoting.preview_coupon(
        plan_id=payload.plan_id, code=payload.code, user_id=user.id
    )


# -- checkout --------------------------------------------------------------


@router.post("/checkout/wallet", summary="Pay for a plan from the wallet")
async def checkout_wallet(
    payload: PlanRequest, user: CurrentMiniAppUser, services: ServicesDep, uow: UnitOfWorkDep
) -> Any:
    card = await services.checkout.pay_from_wallet(
        user.id, plan_id=payload.plan_id, coupon_code=payload.coupon_code
    )
    await uow.commit()
    return {"subscription_id": str(card.subscription_id)}


@router.post("/checkout/card", summary="Start a card-to-card payment")
async def checkout_card(
    payload: PlanRequest, user: CurrentMiniAppUser, services: ServicesDep, uow: UnitOfWorkDep
) -> Any:
    details = await services.checkout.begin_card(
        user.id, plan_id=payload.plan_id, coupon_code=payload.coupon_code
    )
    await uow.commit()
    return details


@router.post("/checkout/crypto", summary="Start a crypto payment")
async def checkout_crypto(
    payload: PlanRequest, user: CurrentMiniAppUser, services: ServicesDep, uow: UnitOfWorkDep
) -> Any:
    details = await services.checkout.begin_crypto(
        user.id, plan_id=payload.plan_id, coupon_code=payload.coupon_code
    )
    await uow.commit()
    return details


# -- payments --------------------------------------------------------------


@router.post("/payments/{payment_id}/receipt", summary="Attach a card receipt")
async def attach_receipt(
    payment_id: uuid.UUID,
    payload: ReceiptRequest,
    user: CurrentMiniAppUser,
    services: ServicesDep,
    uow: UnitOfWorkDep,
) -> Any:
    payment = await services.checkout.attach_receipt(
        user.id, payment_id=payment_id, file_id=payload.file_id
    )
    await uow.commit()
    return payment


@router.post("/payments/{payment_id}/txid", summary="Attach a crypto transaction hash")
async def attach_txid(
    payment_id: uuid.UUID,
    payload: TxidRequest,
    user: CurrentMiniAppUser,
    services: ServicesDep,
    uow: UnitOfWorkDep,
) -> Any:
    payment = await services.checkout.attach_txid(user.id, payment_id=payment_id, txid=payload.txid)
    await uow.commit()
    return payment


@router.post(
    "/payments/{payment_id}/receipt-request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask the bot to collect the receipt for this payment",
)
async def request_receipt(
    payment_id: uuid.UUID, user: CurrentMiniAppUser, container: ContainerDep
) -> dict[str, Any]:
    """Send the customer a prompt in the chat, and remember what it was about.

    The Mini App cannot upload to Telegram's file storage, so the receipt has
    to arrive in the bot chat. Closing the app and hoping was the old
    behaviour, and it left people staring at a conversation that had said
    nothing to them.

    The intent is written before the prompt is sent, because the customer can
    reply faster than we can lose the race. It is a hint and nothing more - the
    bot still checks the payment is theirs and still unproven.
    """
    telegram_id = user.telegram_id
    stored_id = payment_id.hex

    def find(scope: SyncScope) -> Payment | None:
        for candidate in scope.payments.list_for_user(telegram_id, limit=_PENDING_LIMIT):
            if candidate.id == stored_id and candidate.state is PaymentState.AWAITING_PROOF:
                return candidate
        return None

    payment = await read_scope(container, find)
    if payment is None:
        # 404 for "not yours" as well as "not waiting", so the response cannot
        # be used to discover which payment ids exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No payment is awaiting a receipt.")

    await container.cache.set(
        receipt_intent_key(telegram_id), stored_id, ttl_seconds=RECEIPT_INTENT_TTL_SECONDS
    )

    amount = payment.amount.amount

    def notify(scope: SyncScope) -> None:
        scope.engine.notify(
            user_id=telegram_id,
            template_key=RECEIPT_REQUESTED_TEMPLATE,
            fields={"amount": amount},
        )

    await mutate_scope(container, notify)
    return {"sent": True}


@router.get("/payments/pending", summary="Payments still awaiting proof or review")
async def pending_payments(user: CurrentMiniAppUser, container: ContainerDep) -> Any:
    """Everything this customer still owes us proof for, or we owe them a decision on.

    Settled and terminal payments are filtered out here rather than in SQL: the
    two predicates already live on the enum, and duplicating them in a WHERE
    clause is how the list and the badge start disagreeing.
    """
    telegram_id = user.telegram_id

    def work(scope: SyncScope) -> list[dict[str, Any]]:
        payments = scope.payments.list_for_user(telegram_id, limit=_PENDING_LIMIT)
        return [
            _payment_view(payment, scope)
            for payment in payments
            if not payment.state.is_settled() and not payment.state.is_terminal()
        ]

    return await read_scope(container, work)


# -- subscriptions ---------------------------------------------------------


@router.get("/subscriptions", summary="This customer's services")
async def subscriptions(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.subscriptions.list_for_user(user.id)


@router.post("/subscriptions/{subscription_id}/rotate", summary="Issue a fresh link")
async def rotate_link(
    subscription_id: uuid.UUID,
    user: CurrentMiniAppUser,
    services: ServicesDep,
    uow: UnitOfWorkDep,
) -> Any:
    """Still unimplemented, and the reason is a missing panel capability.

    Rotating a link means asking the panel to reissue the subscription token.
    No adapter exposes that - `PanelAdapter` can read a subscription but not
    regenerate one - so honouring this would mean adding a capability across
    six panel implementations, each with a different API, none of which can be
    verified without the panels themselves.

    Answering 501 rather than returning the existing card is the whole point:
    telling a customer their leaked link was replaced while it still works is
    worse than telling them the button does not work yet.
    """
    try:
        card = await services.subscriptions.rotate_link(user.id, subscription_id)
    except NotImplementedError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    await uow.commit()
    return card


@router.get(
    "/subscriptions/{subscription_id}/renewal-options",
    summary="Plans this subscription can renew onto",
)
async def renewal_options(subscription_id: str, user: CurrentMiniAppUser, scope: ScopeDep) -> Any:
    """Every published plan on the same product, priced for this customer.

    Scoped to the product rather than the whole catalogue: renewing is meant to
    keep or upgrade the package someone already has, and offering an unrelated
    product here is a different purchase wearing a renewal button.
    """
    subscription = await scope.subscriptions.get(subscription_id)
    if subscription is None or subscription.user_id != user.telegram_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Subscription not found.")

    plan = await scope.catalog_plans.get(uuid.UUID(subscription.plan_id))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="The plan no longer exists.")

    siblings = await scope.catalog_plans.list_for_product(plan.product_id, published_only=True)
    return [
        await scope.quoting.quote_view(plan_id=sibling.id, user_id=user.id) for sibling in siblings
    ]


# -- wallet ----------------------------------------------------------------


@router.get("/wallet", summary="Balance and lifetime spend")
async def wallet(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.wallet.snapshot(user.id)


@router.get("/wallet/transactions", summary="Wallet history, newest first")
async def wallet_transactions(
    user: CurrentMiniAppUser,
    services: ServicesDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Any:
    items = await services.wallet.transactions(
        user.id, limit=page_size, offset=(page - 1) * page_size
    )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": await services.wallet.transaction_count(user.id),
    }


@router.post("/wallet/topup", summary="Start a wallet top-up")
async def topup(
    payload: TopupRequest, user: CurrentMiniAppUser, services: ServicesDep, uow: UnitOfWorkDep
) -> Any:
    details = await services.checkout.begin_topup(
        user.id, amount=payload.amount, method=payload.method
    )
    await uow.commit()
    return details


# -- referral, tickets, profile, preferences, status -----------------------


@router.get("/referral", summary="Invite code and its results")
async def referral(
    user: CurrentMiniAppUser, services: ServicesDep, scope: ScopeDep
) -> Any:
    """The customer's own results, plus the terms they are being offered.

    The rates are admin-configurable settings rather than constants, so the
    invite screen has to read them rather than state them. It was rendering
    "NaN%" for both of them and a NaN toman bonus.
    """
    summary = await services.referrals.summary(user.id)
    policy = await scope.pricing_policies.load()
    return dataclasses.asdict(summary) | {
        "invitee_bonus": policy.referral.invitee_bonus.amount,
        "first_purchase_bps": policy.referral.first_purchase_bps,
        "recurring_bps": policy.referral.recurring_bps,
    }


@router.get("/tickets", summary="This customer's support tickets")
async def tickets(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.tickets.list_for_user(user.id)


@router.post("/tickets", summary="Open a support ticket")
async def open_ticket(
    payload: OpenTicketRequest,
    user: CurrentMiniAppUser,
    services: ServicesDep,
    uow: UnitOfWorkDep,
) -> Any:
    try:
        card = await services.tickets.open_ticket(
            user.id, topic=payload.subject or payload.topic, message=payload.message
        )
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await uow.commit()
    return card


@router.get("/tickets/{ticket_id}/messages", summary="One ticket's thread")
async def ticket_messages(
    ticket_id: uuid.UUID, user: CurrentMiniAppUser, container: ContainerDep
) -> Any:
    """Internal notes are excluded, and the ticket must belong to the caller."""
    telegram_id = user.telegram_id
    # Stored ids are hex without dashes; the Mini App holds the parsed form,
    # because that is what the ticket list sends it. `str()` on the way back
    # puts the dashes in and the lookup finds nothing - which is the third
    # place this exact mistake has surfaced.
    stored = ticket_id.hex

    def work(scope: SyncScope) -> list[dict[str, Any]]:
        _require_own_ticket(scope, stored, telegram_id)
        return [_message_view(m) for m in scope.support.get_messages(stored)]

    return await read_scope(container, work)


@router.post("/tickets/{ticket_id}/messages", summary="Reply to a ticket")
async def reply_to_ticket(
    ticket_id: uuid.UUID,
    payload: TicketReplyRequest,
    user: CurrentMiniAppUser,
    container: ContainerDep,
) -> Any:
    telegram_id = user.telegram_id
    body = payload.message

    stored = ticket_id.hex

    def work(scope: SyncScope) -> dict[str, Any]:
        _require_own_ticket(scope, stored, telegram_id)
        return _message_view(
            scope.support.customer_reply(
                ReplyRequest(ticket_id=stored, body_fa=body, author_id=telegram_id)
            )
        )

    return await mutate_scope(container, work)


@router.get("/profile", summary="Profile summary")
async def profile(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    """The profile, plus the two numbers the tier ladder is drawn from.

    Lifetime spend is a wallet fact, not a user column, so the profile
    reader has never been able to fill it in - it returned zero, and the
    ladder showed every customer as bronze with nothing spent. Composing
    the two read models here is cheaper than teaching the profile reader to
    reach across into the payments scope.
    """
    summary = await services.profiles.summary(user.id)
    wallet = await services.wallet.snapshot(user.id)
    return dataclasses.asdict(summary) | {
        "lifetime_spend": wallet.lifetime_spend,
        "tier": wallet.tier.value,
    }


@router.post("/profile", summary="Update the display name")
async def update_profile(
    payload: ProfileRequest,
    user: CurrentMiniAppUser,
    services: ServicesDep,
    uow: UnitOfWorkDep,
) -> Any:
    summary = await services.profiles.set_display_name(user.id, payload.display_name)
    await uow.commit()
    return summary


@router.get("/preferences", summary="Notification switches")
async def preferences(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.preferences.load(user.id)


@router.post("/preferences", summary="Save notification switches")
async def save_preferences(
    payload: PreferencesRequest, user: CurrentMiniAppUser, services: ServicesDep
) -> Any:
    return await services.preferences.save(
        user.id,
        NotificationPreferences(
            expiry=payload.expiry,
            traffic=payload.traffic,
            promos=payload.promos,
            news=payload.news,
            quiet_hours=payload.quiet_hours,
        ),
    )


@router.get("/servers", summary="Server status")
async def servers(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.servers.rows()


@router.get("/faq", summary="Frequently asked questions")
async def faq(user: CurrentMiniAppUser) -> Any:
    """Static Persian copy, served from the same source the bot renders."""
    from geekvpn.presentation.bot import faq_content as F

    return [
        {
            "key": section.key,
            "title_fa": section.title_fa,
            "entries": [
                {
                    "key": entry.key,
                    "question_fa": entry.question_fa,
                    "answer_fa": entry.answer_fa,
                }
                for entry in section.entries
            ],
        }
        for section in F.FAQ
    ]
