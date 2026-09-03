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
from pydantic import ConfigDict, Field

from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.errors import SubscriptionNotFound
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/subscriptions", tags=["administration"])


class SubscriptionResponse(ApiModel):
    id: str
    user_id: int
    #: Null for a service nobody bought here - an account sold through
    #: support and claimed in the bot. Declaring these required would
    #: have made every such row a 500 on the operator's own screen.
    order_id: str | None
    plan_id: str | None
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


# -- operator actions ------------------------------------------------------
#
# Every one of these existed on the aggregate and on the panel adapters and was
# called by nothing, so an operator's only options were "read it" and "read its
# usage again". A shared customer link, a week owed for an outage, an account
# to close: all of them were a SQL statement and a hand-edited panel.


class ReasonRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: Recorded on the subscription. An account closed for no stated reason is
    #: a support ticket nobody can answer six weeks later.
    reason_fa: str = Field(min_length=3, max_length=200)


class ExtendRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    #: A year at a time is generous; anything beyond it is a typo, and a typo
    #: here gives away a decade of service.
    days: int = Field(gt=0, le=365)


class AddTrafficRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    gib: int = Field(gt=0, le=10_000)


async def _act(scope: ScopeDep, action: str, subscription_id: str, **kwargs: object) -> Subscription:
    """Run one operator action, turning its two failure modes into HTTP.

    A `PanelError` is the panel being unreachable or refusing, which is news
    for the operator rather than a fault in this service - 502, with the
    panel's own message, and our record left exactly as it was.
    """
    try:
        method = getattr(scope.subscription_admin, action)
        return await method(subscription_id, **kwargs)  # type: ignore[no-any-return]
    except SubscriptionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Subscription not found.") from exc
    except PanelError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/{subscription_id}/suspend",
    response_model=SubscriptionResponse,
    summary="Cut off access without deleting the account",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def suspend_subscription(
    subscription_id: str, payload: ReasonRequest, scope: ScopeDep
) -> SubscriptionResponse:
    return SubscriptionResponse.of(
        await _act(scope, "suspend", subscription_id, reason_fa=payload.reason_fa)
    )


@router.post(
    "/{subscription_id}/resume",
    response_model=SubscriptionResponse,
    summary="Restore access to a suspended subscription",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def resume_subscription(subscription_id: str, scope: ScopeDep) -> SubscriptionResponse:
    return SubscriptionResponse.of(await _act(scope, "resume", subscription_id))


@router.post(
    "/{subscription_id}/revoke",
    response_model=SubscriptionResponse,
    summary="Delete the panel account and close the subscription",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def revoke_subscription(
    subscription_id: str, payload: ReasonRequest, scope: ScopeDep
) -> SubscriptionResponse:
    """The row stays. An order, a payment and any refund all point at it, and
    deleting it would leave three records naming a subscription that never
    existed."""
    return SubscriptionResponse.of(
        await _act(scope, "revoke", subscription_id, reason_fa=payload.reason_fa)
    )


@router.post(
    "/{subscription_id}/extend",
    response_model=SubscriptionResponse,
    summary="Add days, without charging for them",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def extend_subscription(
    subscription_id: str, payload: ExtendRequest, scope: ScopeDep
) -> SubscriptionResponse:
    return SubscriptionResponse.of(await _act(scope, "extend", subscription_id, days=payload.days))


@router.post(
    "/{subscription_id}/add-traffic",
    response_model=SubscriptionResponse,
    summary="Raise the traffic cap",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def add_traffic(
    subscription_id: str, payload: AddTrafficRequest, scope: ScopeDep
) -> SubscriptionResponse:
    return SubscriptionResponse.of(await _act(scope, "add_traffic", subscription_id, gib=payload.gib))


@router.post(
    "/{subscription_id}/reset-traffic",
    response_model=SubscriptionResponse,
    summary="Set usage back to zero",
    dependencies=[Depends(requires(Permission.SUBSCRIPTIONS_WRITE))],
)
async def reset_traffic(subscription_id: str, scope: ScopeDep) -> SubscriptionResponse:
    return SubscriptionResponse.of(await _act(scope, "reset_traffic", subscription_id))
