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
from pydantic import BaseModel, ConfigDict, Field

from geekvpn.application.bot.read_models import NotificationPreferences
from geekvpn.domain.base.errors import DomainError
from geekvpn.presentation.api.dependencies import UnitOfWorkDep
from geekvpn.presentation.api.miniapp_security import CurrentMiniAppUser, ServicesDep
from geekvpn.presentation.api.security import ScopeDep

router = APIRouter(prefix="/api/miniapp", tags=["mini-app"])


# -- request bodies --------------------------------------------------------


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    coupon_code: str | None = Field(default=None, max_length=64)


class CouponPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    code: str = Field(min_length=1, max_length=64)


class TopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0)
    method: str = Field(pattern="^(card|crypto)$")


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=512)


class TxidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    txid: str = Field(min_length=8, max_length=256)


class OpenTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=128)
    subject: str = Field(default="", max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class TicketReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=64)


class PreferencesRequest(BaseModel):
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
async def pending_payments(user: CurrentMiniAppUser, services: ServicesDep) -> Any:
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Listing pending payments needs a reader; see docs/next-tasks.md.",
    )


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
async def renewal_options(
    subscription_id: uuid.UUID, user: CurrentMiniAppUser, scope: ScopeDep
) -> Any:
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Renewal options need a reader; see docs/next-tasks.md.",
    )


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
async def ticket_messages(
    ticket_id: uuid.UUID, user: CurrentMiniAppUser, services: ServicesDep
) -> Any:
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Reading a ticket thread needs a reader; see docs/next-tasks.md.",
    )


@router.post("/tickets/{ticket_id}/messages", summary="Reply to a ticket")
async def reply_to_ticket(
    ticket_id: uuid.UUID,
    payload: TicketReplyRequest,
    user: CurrentMiniAppUser,
    services: ServicesDep,
) -> Any:
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Replying needs a customer-side reply port; see docs/next-tasks.md.",
    )


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
