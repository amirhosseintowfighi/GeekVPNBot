"""Subscription administration.

``sync-usage`` is the operator's answer to "the customer says they have used
nothing and we say they have used 40GB". It reads the figure back from the panel
through the same :class:`UsageSyncService` the scheduled job uses, so the manual
button and the automatic sweep can never disagree about what a reading means.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/subscriptions", tags=["administration"])


class SubscriptionResponse(ApiModel):
    id: str
    user_id: int
    order_id: str
    plan_id: str
    state: SubscriptionState
    node_id: str | None
    remote_username: str | None
    subscription_url: str | None
    started_at: datetime
    expires_at: datetime
    traffic_limit_mib: int | None
    traffic_used_mib: int
    device_limit: int
    last_synced_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, sub: Subscription) -> SubscriptionResponse:
        return cls(
            id=sub.id,
            user_id=sub.user_id,
            order_id=sub.order_id,
            plan_id=sub.plan_id,
            state=sub.state,
            node_id=sub.node_id,
            remote_username=sub.remote_username,
            subscription_url=sub.subscription_url,
            started_at=sub.started_at,
            expires_at=sub.expires_at,
            traffic_limit_mib=sub.traffic_limit_mib,
            traffic_used_mib=sub.traffic_used_mib,
            device_limit=sub.device_limit,
            last_synced_at=sub.last_synced_at,
            revoked_at=sub.revoked_at,
        )


class SubscriptionPage(ApiModel):
    items: list[SubscriptionResponse]
    total: int


class SyncUsageResponse(ApiModel):
    ok: bool
    subscription: SubscriptionResponse | None = None
    message: str | None = None


@router.get(
    "",
    response_model=SubscriptionPage,
    summary="List subscriptions",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_READ))],
)
async def list_subscriptions(
    scope: ScopeDep,
    state: SubscriptionState | None = None,
    user_id: int | None = None,
    node_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SubscriptionPage:
    subs, total = await scope.subscriptions.search(
        state=state, user_id=user_id, node_id=node_id, limit=limit, offset=offset
    )
    return SubscriptionPage(items=[SubscriptionResponse.of(s) for s in subs], total=total)


@router.get(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="One subscription",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_READ))],
)
async def get_subscription(subscription_id: str, scope: ScopeDep) -> SubscriptionResponse:
    sub = await scope.subscriptions.get(subscription_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Subscription not found.")
    return SubscriptionResponse.of(sub)


@router.post(
    "/{subscription_id}/sync-usage",
    response_model=SyncUsageResponse,
    summary="Read traffic usage back from the panel",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def sync_usage(subscription_id: str, scope: ScopeDep) -> SyncUsageResponse:
    if await scope.subscriptions.get(subscription_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Subscription not found.")

    try:
        updated = await scope.usage_sync.sync_subscription(subscription_id)
    except PanelError as exc:
        # The panel being down is news for the operator, not a server fault.
        return SyncUsageResponse(ok=False, message=str(exc))

    if updated is None:
        return SyncUsageResponse(
            ok=False, message="This subscription has no panel account to read."
        )
    return SyncUsageResponse(ok=True, subscription=SubscriptionResponse.of(updated))
