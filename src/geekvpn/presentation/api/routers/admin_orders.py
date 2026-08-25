"""Order administration.

The interesting route is ``retry-provision``. When a panel was unreachable at
the moment a payment cleared, the order sits in a failed state with the money
already captured - the single worst state this platform can be in. This is the
button that resolves it, and it calls the same
:meth:`ProvisioningService.provision` the automatic path uses rather than a
parallel recovery routine, because a recovery path that differs from the normal
path is a recovery path nobody has tested.

``provision`` is idempotent, so pressing the button twice is harmless.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.domain.provisioning.order import Order
from geekvpn.infrastructure.persistence.repositories.sync_directory import Person
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/orders", tags=["administration"])


class OrderResponse(ApiModel):
    id: str
    number: str
    user_id: int
    #: Who placed it. `None` only when the id belongs to no user row we still
    #: have; the id itself is always there, so the row stays usable.
    customer_name: str | None = None
    customer_username: str | None = None
    state: OrderState
    plan_id: str
    plan_name_fa: str
    duration_days: int
    traffic_mib: int | None
    device_limit: int
    list_price: int
    discount: int
    total: int
    coupon_code: str | None
    is_renewal: bool
    placed_at: datetime
    paid_at: datetime | None
    provisioned_at: datetime | None
    failure_reason: str | None

    @classmethod
    def of(cls, order: Order, person: Person | None = None) -> OrderResponse:
        return cls(
            id=order.id,
            number=order.number,
            user_id=order.user_id,
            customer_name=person.display_name if person else None,
            customer_username=person.username if person else None,
            state=order.state,
            plan_id=order.plan_id,
            plan_name_fa=order.plan_name_fa,
            duration_days=order.duration_days,
            traffic_mib=order.traffic_mib,
            device_limit=order.device_limit,
            list_price=order.list_price.amount,
            discount=order.discount.amount,
            total=order.total.amount,
            coupon_code=order.coupon_code,
            is_renewal=order.is_renewal,
            placed_at=order.placed_at,
            paid_at=order.paid_at,
            provisioned_at=order.provisioned_at,
            failure_reason=order.failure_reason,
        )


class OrderPage(ApiModel):
    items: list[OrderResponse]
    total: int


class RetryProvisionResponse(ApiModel):
    ok: bool
    subscription_id: str | None = None
    message: str | None = None


@router.get(
    "",
    response_model=OrderPage,
    summary="List orders, newest first",
    dependencies=[Depends(requires(Permission.ORDERS_READ))],
)
async def list_orders(
    scope: ScopeDep,
    state: OrderState | None = None,
    user_id: int | None = None,
    number: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    orders, total = await scope.orders.search(
        state=state, user_id=user_id, number=number, limit=limit, offset=offset
    )
    # One lookup for the page. Per row it is an extra round trip each, on a
    # list an operator scans rather than reads.
    people = await scope.users.people_by_telegram_ids(order.user_id for order in orders)
    return OrderPage(
        items=[OrderResponse.of(order, people.get(order.user_id)) for order in orders],
        total=total,
    )


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="One order",
    dependencies=[Depends(requires(Permission.ORDERS_READ))],
)
async def get_order(order_id: str, scope: ScopeDep) -> OrderResponse:
    order = await scope.orders.get(order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found.")
    people = await scope.users.people_by_telegram_ids([order.user_id])
    return OrderResponse.of(order, people.get(order.user_id))


@router.post(
    "/{order_id}/retry-provision",
    response_model=RetryProvisionResponse,
    summary="Re-run provisioning for a paid order",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def retry_provision(order_id: str, scope: ScopeDep) -> RetryProvisionResponse:
    """A provisioning failure answers 200 with ``ok: false``.

    The operator asked "what happens if I retry", and "the panel is still
    refusing" is a successful answer to that question. Turning it into a 5xx
    would make the panel's outage look like ours.
    """
    if await scope.orders.get(order_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found.")

    try:
        subscription = await scope.provisioning.provision(order_id)
    except DomainError as exc:
        return RetryProvisionResponse(ok=False, message=str(exc))
    return RetryProvisionResponse(ok=True, subscription_id=subscription.id)
