"""Reviewing reseller applications, and redeeming a first-password link.

Two audiences in one file, and one of them is not signed in.

`/set-password` is deliberately unauthenticated: the person using it has no way
to get a session yet, which is the entire reason the link exists. It is
protected by the token instead - long, single-use, short-lived, and stored only
as a hash - and by the rate limit its prefix carries.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ConfigDict, Field

from geekvpn.application.resellers.applications import (
    AlreadyApplied,
    ApplicationNotFound,
)
from geekvpn.application.resellers.password_setup import (
    MIN_PASSWORD_LENGTH,
    InvalidSetupToken,
)
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.resellers.reseller import MAX_DISCOUNT_PERCENT
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import CurrentAdmin, ScopeDep, requires

router = APIRouter(prefix="/admin/reseller-applications", tags=["administration"])
#: Deliberately *not* under `/admin`.
#:
#: The admin IP allowlist protects everything with that prefix, and a reseller
#: redeeming their link is on a home connection - so under `/admin` this would
#: work in testing, where no allowlist is configured, and refuse every real
#: reseller the moment one was. It is also not an admin-console endpoint: it is
#: a public credential redemption that happens to end in an admin account.
public_router = APIRouter(prefix="/auth", tags=["admin-authentication"])


class ApplicationResponse(ApiModel):
    id: uuid.UUID
    telegram_id: int
    name_fa: str
    contact_fa: str | None
    note_fa: str | None
    state: str
    created_at: datetime


class ApprovedResponse(ApiModel):
    """What an approval produced.

    `setup_token` is the one-time secret for the link. It is returned here and
    nowhere else, and stored only as a hash - an operator who loses it approves
    nothing again, they issue a new link.
    """

    reseller_id: uuid.UUID
    admin_id: uuid.UUID
    username: str
    setup_token: str


class ApproveRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    discount_percent: int = Field(default=0, ge=0, le=MAX_DISCOUNT_PERCENT)


class RejectRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    reason_fa: str = Field(default="", max_length=512)


class SetPasswordRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    admin_id: uuid.UUID
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


@router.get(
    "",
    response_model=list[ApplicationResponse],
    dependencies=[Depends(requires(Permission.RESELLERS_READ))],
)
async def list_applications(scope: ScopeDep) -> list[ApplicationResponse]:
    return [
        ApplicationResponse(
            id=row.id,
            telegram_id=row.telegram_id,
            name_fa=row.name_fa,
            contact_fa=row.contact_fa,
            note_fa=row.note_fa,
            state=row.state,
            created_at=row.created_at,
        )
        for row in await scope.reseller_applications.pending()
    ]


@router.post(
    "/{application_id}/approve",
    response_model=ApprovedResponse,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def approve(
    application_id: uuid.UUID,
    payload: ApproveRequest,
    scope: ScopeDep,
    admin: CurrentAdmin,
) -> ApprovedResponse:
    """Say yes, and leave a reseller who can actually sell."""
    try:
        approval = await scope.reseller_applications.approve(
            application_id, discount_percent=payload.discount_percent
        )
    except ApplicationNotFound as failure:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(failure)) from failure
    except AlreadyApplied as failure:
        raise HTTPException(status.HTTP_409_CONFLICT, str(failure)) from failure

    return ApprovedResponse(
        reseller_id=approval.reseller.id,
        admin_id=approval.reseller.admin_id,
        username=approval.username,
        setup_token=approval.setup_token,
    )


@router.post(
    "/{application_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires(Permission.RESELLERS_WRITE))],
)
async def reject(
    application_id: uuid.UUID, payload: RejectRequest, scope: ScopeDep
) -> None:
    try:
        await scope.reseller_applications.reject(
            application_id, reason_fa=payload.reason_fa
        )
    except ApplicationNotFound as failure:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(failure)) from failure


@public_router.post("/set-password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(payload: SetPasswordRequest, scope: ScopeDep) -> None:
    """Redeem a one-time link for a first password.

    No session required, and none issued: the person then signs in the ordinary
    way, which is one fewer path that mints a credential.
    """
    try:
        await scope.password_setup.redeem(
            payload.admin_id, token=payload.token, password=payload.password
        )
    except InvalidSetupToken as failure:
        # One message for wrong, expired, spent and unknown. Distinguishing
        # them tells an attacker which accounts exist and which have a link
        # waiting to be taken.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(failure)) from failure
    except ValueError as failure:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(failure)) from failure
