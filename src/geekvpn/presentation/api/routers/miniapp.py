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

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ConfigDict, Field

from geekvpn.application.bot.read_models import NotificationPreferences
from geekvpn.application.support.ticket_service import MessageView, ReplyRequest
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.payments.payment import Payment
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import mutate_scope, read_scope
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep, UnitOfWorkDep
from geekvpn.presentation.api.miniapp_security import CurrentMiniAppUser, ServicesDep
from geekvpn.presentation.api.security import ScopeDep

router = APIRouter(prefix="/api/miniapp", tags=["mini-app"])

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
        "body_fa": message.body_fa,
        "created_at": message.created_at,
        "attachment_count": message.attachment_count,
        "is_read": message.is_read,
    }


def _payment_view(payment: Payment) -> dict[str, Any]:
    """The card number and the receipt digest deliberately stay server-side."""
    return {
        "payment_id": payment.id,
        "reference": payment.id,
        "amount": payment.amount.amount,
        "method": payment.method.value,
        "state": payment.state.value,
        "created_at": payment.created_at,
        "expires_at": payment.expires_at,
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


@router.get("/storefront", summary="Categories, products and priced plans")
async def storefront(user: CurrentMiniAppUser, scope: ScopeDep) -> Any:
    view = await scope.storefront.load(user_id=user.id)
    return view


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
            _payment_view(payment)
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
async def referral(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.referrals.summary(user.id)


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
async def ticket_messages(ticket_id: str, user: CurrentMiniAppUser, container: ContainerDep) -> Any:
    """Internal notes are excluded, and the ticket must belong to the caller."""
    telegram_id = user.telegram_id

    def work(scope: SyncScope) -> list[dict[str, Any]]:
        _require_own_ticket(scope, ticket_id, telegram_id)
        return [_message_view(m) for m in scope.support.get_messages(ticket_id)]

    return await read_scope(container, work)


@router.post("/tickets/{ticket_id}/messages", summary="Reply to a ticket")
async def reply_to_ticket(
    ticket_id: str,
    payload: TicketReplyRequest,
    user: CurrentMiniAppUser,
    container: ContainerDep,
) -> Any:
    telegram_id = user.telegram_id
    body = payload.message

    def work(scope: SyncScope) -> dict[str, Any]:
        _require_own_ticket(scope, ticket_id, telegram_id)
        return _message_view(
            scope.support.customer_reply(
                ReplyRequest(ticket_id=ticket_id, body_fa=body, author_id=telegram_id)
            )
        )

    return await mutate_scope(container, work)


@router.get("/profile", summary="Profile summary")
async def profile(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    return await services.profiles.summary(user.id)


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
