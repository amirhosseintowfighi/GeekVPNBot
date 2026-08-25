"""Customer administration.

Distinct from ``admin_users.py``, which manages *operators*. The naming in this
codebase is that an "admin" is staff and a "customer" is an end user, and the
two live behind different permissions: ``USERS_*`` here, ``ADMINS_*`` there.

Suspension is reversible and always carries a reason. A blocked account with no
recorded reason is one support ticket nobody can answer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ConfigDict, Field

from geekvpn.domain.identity.enums import UserStatus
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.identity.user import User
from geekvpn.domain.notifications.enums import NotificationCategory
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import mutate_scope
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/customers", tags=["administration"])


class CustomerResponse(ApiModel):
    id: uuid.UUID
    telegram_id: int
    username: str | None
    display_name: str
    status: UserStatus
    is_premium: bool
    referral_code: str
    referred_by_code: str | None
    suspended_reason: str | None
    last_seen_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> CustomerResponse:
        return cls(
            id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            display_name=user.display_name,
            status=user.status,
            is_premium=user.is_premium,
            referral_code=user.referral_code,
            referred_by_code=user.referred_by_code,
            suspended_reason=user.suspended_reason,
            last_seen_at=user.last_seen_at,
            created_at=user.created_at,
        )


class CustomerPage(ApiModel):
    items: list[CustomerResponse]
    total: int


class CustomerDetail(ApiModel):
    customer: CustomerResponse
    subscriptions: int
    orders: int


class SuspendRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=512)


@router.get(
    "",
    response_model=CustomerPage,
    summary="List customers",
    dependencies=[Depends(requires(Permission.USERS_READ))],
)
async def list_customers(
    scope: ScopeDep,
    status_filter: Annotated[UserStatus | None, Query(alias="status")] = None,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerPage:
    users, total = await scope.users.search(
        status=status_filter, query=query, limit=limit, offset=offset
    )
    return CustomerPage(items=[CustomerResponse.of(u) for u in users], total=total)


@router.get(
    "/{customer_id}",
    response_model=CustomerDetail,
    summary="One customer, with their counts",
    dependencies=[Depends(requires(Permission.USERS_READ))],
)
async def get_customer(customer_id: uuid.UUID, scope: ScopeDep) -> CustomerDetail:
    user = await scope.users.get(customer_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    _, subscription_count = await scope.subscriptions.search(user_id=user.telegram_id, limit=1)
    order_count = await scope.orders.count_for_user(user.telegram_id)
    return CustomerDetail(
        customer=CustomerResponse.of(user),
        subscriptions=subscription_count,
        orders=order_count,
    )


@router.post(
    "/{customer_id}/suspend",
    response_model=CustomerResponse,
    summary="Block a customer",
    dependencies=[Depends(requires(Permission.USERS_SUSPEND))],
)
async def suspend_customer(
    customer_id: uuid.UUID, payload: SuspendRequest, scope: ScopeDep
) -> CustomerResponse:
    user = await scope.users.get(customer_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    user.suspend(reason=payload.reason)
    await scope.users.update(user)
    return CustomerResponse.of(user)


@router.post(
    "/{customer_id}/reinstate",
    response_model=CustomerResponse,
    summary="Unblock a customer",
    dependencies=[Depends(requires(Permission.USERS_SUSPEND))],
)
async def reinstate_customer(customer_id: uuid.UUID, scope: ScopeDep) -> CustomerResponse:
    user = await scope.users.get(customer_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    user.reinstate()
    await scope.users.update(user)
    return CustomerResponse.of(user)


class DirectMessageRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    title_fa: str = Field(min_length=1, max_length=120)
    body_fa: str = Field(min_length=1, max_length=2000)


@router.post(
    "/{customer_id}/message",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Write to one customer",
    dependencies=[Depends(requires(Permission.BROADCAST_SEND))],
)
async def message_customer(
    customer_id: uuid.UUID,
    payload: DirectMessageRequest,
    scope: ScopeDep,
    container: ContainerDep,
) -> dict[str, Any]:
    """One message to one person, through the same engine broadcasts use.

    ``CRITICAL`` rather than ``NEWS``: an operator writing to a named customer
    is answering that customer, and a reply that a marketing preference can
    silence is a reply the operator believes they sent. It is the same reason
    the category exists for "your money moved" and "an operator replied".

    The engine also records it, so the next operator to open this customer can
    see what was already said to them instead of repeating it.

    Answering 202 rather than 200: delivery is Telegram's to confirm. What is
    settled by the time this returns is that the message was accepted and
    recorded.
    """
    user = await scope.users.get(customer_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    telegram_id = user.telegram_id
    message = RenderedMessage(
        key="admin.direct",
        category=NotificationCategory.CRITICAL,
        title_fa=payload.title_fa,
        body_fa=payload.body_fa,
    )

    def work(sync: SyncScope) -> dict[str, Any]:
        result = sync.engine.dispatch(
            user_id=telegram_id, message=message, source="admin.direct"
        )
        return {
            "notificationId": result.notification_id,
            "delivered": result.delivered,
            "deferred": result.deferred,
        }

    return await mutate_scope(container, work)
