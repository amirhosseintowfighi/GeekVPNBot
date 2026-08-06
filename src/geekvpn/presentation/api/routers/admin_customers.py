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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from geekvpn.domain.identity.enums import UserStatus
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.identity.user import User
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/customers", tags=["administration"])


class CustomerResponse(BaseModel):
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


class CustomerPage(BaseModel):
    items: list[CustomerResponse]
    total: int


class CustomerDetail(BaseModel):
    customer: CustomerResponse
    subscriptions: int
    orders: int


class SuspendRequest(BaseModel):
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
