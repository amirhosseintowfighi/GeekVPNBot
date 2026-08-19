"""Admin broadcasts: compose, estimate, send, cancel.

The router Phase 10 never got. ``BroadcastService`` was written, tested and
left unreachable because nothing implemented its ``AudienceResolver``; the
admin panel was built against these four routes and every one of them
answered 404.

Two decisions worth stating:

* **Estimating is a separate call, and it is honest.** It resolves the real
  audience with the real rules rather than approximating a count, because the
  number an operator sees immediately before pressing send is the number they
  are agreeing to message.
* **Sending is synchronous and idempotent.** A broadcast is one pass over a
  resolved list, batched and committed as it goes, so a double-submitted
  request must not start a second pass over the same people - hence the
  Idempotency-Key, the same one every other money-or-message route requires.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import ConfigDict, Field

from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.notifications.broadcast import MAX_BODY, MIN_BODY, MIN_TITLE, Broadcast
from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    NotificationCategory,
)
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import (
    ADMIN_PAGE_SIZE,
    ActorId,
    IdempotencyKey,
    PageQuery,
    claim_idempotency,
    mutate_scope,
    read_scope,
)
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import CurrentAdmin, requires

router = APIRouter(prefix="/admin/broadcasts", tags=["broadcast"])


class AudienceBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    segment: AudienceKind
    #: Only meaningful for `tier` (a loyalty tier) and `explicit` (a
    #: comma-separated list of Telegram ids).
    reference: str | None = None


class ComposeBody(AudienceBody):
    title_fa: str = Field(min_length=MIN_TITLE, max_length=256)
    body_fa: str = Field(min_length=MIN_BODY, max_length=MAX_BODY)
    category: NotificationCategory = NotificationCategory.NEWS
    #: Send immediately. False leaves it a draft an operator can review.
    send_now: bool = True


def _view(broadcast: Broadcast) -> dict[str, Any]:
    return {
        "id": broadcast.id,
        "titleFa": broadcast.title_fa,
        "bodyFa": broadcast.body_fa,
        "segmentLabelFa": broadcast.audience.label_fa(),
        "segment": str(broadcast.audience),
        "category": str(broadcast.category),
        "state": str(broadcast.state),
        "audienceSize": broadcast.recipient_count,
        "deliveredCount": broadcast.sent,
        "suppressedCount": broadcast.suppressed,
        "failedCount": broadcast.failed,
        "scheduledAt": broadcast.send_at.isoformat() if broadcast.send_at else None,
        "createdAt": broadcast.created_at.isoformat(),
        "startedAt": broadcast.started_at.isoformat() if broadcast.started_at else None,
        "finishedAt": broadcast.finished_at.isoformat() if broadcast.finished_at else None,
        "error": broadcast.error,
    }


@router.get(
    "",
    summary="Broadcasts, newest first",
    dependencies=[Depends(requires(Permission.BROADCAST_READ))],
)
async def list_broadcasts(
    container: ContainerDep,
    admin: CurrentAdmin,
    state: BroadcastState | None = None,
    page: PageQuery = 1,
) -> list[dict[str, Any]]:
    offset = (page - 1) * ADMIN_PAGE_SIZE

    def work(scope: SyncScope) -> list[dict[str, Any]]:
        return [
            _view(broadcast)
            for broadcast in scope.broadcasts.listing(
                state=state, limit=ADMIN_PAGE_SIZE, offset=offset
            )
        ]

    return await read_scope(container, work)


@router.post(
    "/estimate",
    summary="How many people this audience resolves to, right now",
    dependencies=[Depends(requires(Permission.BROADCAST_READ))],
)
async def estimate_audience(
    payload: AudienceBody, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, int]:
    """Resolved for real, not approximated.

    This number is the last thing an operator reads before sending, so it has
    to be the same list the send will walk - same rules, same exclusions.
    """

    def work(scope: SyncScope) -> dict[str, int]:
        recipients = scope.audiences.resolve(payload.segment, reference=payload.reference)
        return {"count": len(recipients)}

    return await read_scope(container, work)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Compose a broadcast, and send it unless told otherwise",
    dependencies=[Depends(requires(Permission.BROADCAST_SEND))],
)
async def create_broadcast(
    payload: ComposeBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label="broadcast.create")

    def work(scope: SyncScope) -> dict[str, Any]:
        broadcast = scope.broadcast_service.create(
            title_fa=payload.title_fa,
            body_fa=payload.body_fa,
            audience=payload.segment,
            audience_ref=payload.reference,
            category=payload.category,
            created_by=actor,
        )
        if payload.send_now:
            scope.broadcast_service.send_now(broadcast.id)
        return _view(scope.broadcasts.get(broadcast.id))

    return await mutate_scope(container, work)


@router.post(
    "/{broadcast_id}/send",
    summary="Send a draft that was composed earlier",
    dependencies=[Depends(requires(Permission.BROADCAST_SEND))],
)
async def send_broadcast(
    broadcast_id: str,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    admin: CurrentAdmin,
) -> dict[str, Any]:
    await claim_idempotency(
        container, idempotency_key, scope_label=f"broadcast.send:{broadcast_id}"
    )

    def work(scope: SyncScope) -> dict[str, Any]:
        scope.broadcast_service.send_now(broadcast_id)
        return _view(scope.broadcasts.get(broadcast_id))

    return await mutate_scope(container, work)


@router.post(
    "/{broadcast_id}/cancel",
    summary="Stop a send in flight",
    dependencies=[Depends(requires(Permission.BROADCAST_SEND))],
)
async def cancel_broadcast(
    broadcast_id: str, container: ContainerDep, actor: ActorId
) -> dict[str, Any]:
    """Stops the remaining batches. It does not unsend what has already gone."""

    def work(scope: SyncScope) -> dict[str, Any]:
        scope.broadcast_service.cancel(broadcast_id, cancelled_by=actor)
        return _view(scope.broadcasts.get(broadcast_id))

    return await mutate_scope(container, work)


__all__ = ["router"]
