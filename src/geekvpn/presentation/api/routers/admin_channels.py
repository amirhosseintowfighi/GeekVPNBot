"""Channels the platform's own bot makes customers join.

A reseller's are the same shape, on their own routes, in `reseller.py` - the
scope is what differs and it comes from the token, never from the request. One
endpoint taking a shop id would be one missing check away from a reseller
editing our gate.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ConfigDict, Field

from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/channels", tags=["settings"])

READ = Depends(requires(Permission.SETTINGS_READ))
WRITE = Depends(requires(Permission.SETTINGS_WRITE))

#: `@name` or a numeric chat id. Telegram takes either wherever a chat is
#: named, and rejecting one of them here would rule out private channels, which
#: are the ones most shops actually gate on.
CHAT_REF = r"^(@[A-Za-z][A-Za-z0-9_]{4,31}|-?\d{5,20})$"


class ChannelResponse(ApiModel):
    id: str
    chat_ref: str
    title_fa: str
    invite_url: str | None
    active: bool
    sort_order: int


class NewChannel(ApiModel):
    model_config = ConfigDict(extra="forbid")

    chat_ref: str = Field(pattern=CHAT_REF)
    title_fa: str = Field(min_length=1, max_length=128)
    #: Required in practice for a private channel: `-100...` cannot be turned
    #: into a link, so without this there is a requirement and no way to meet
    #: it. Validated at the edge rather than trusted.
    invite_url: str | None = Field(default=None, max_length=512)


class ActiveRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


@router.get("", response_model=list[ChannelResponse], dependencies=[READ])
async def list_channels(scope: ScopeDep) -> list[ChannelResponse]:
    return [ChannelResponse(**row) for row in await scope.required_channels.listing()]


@router.post("", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE])
async def add_channel(payload: NewChannel, scope: ScopeDep) -> None:
    reject_unreachable(payload)
    await scope.required_channels.add(
        chat_ref=payload.chat_ref,
        title_fa=payload.title_fa,
        invite_url=payload.invite_url,
    )


@router.post(
    "/{channel_id}/active", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE]
)
async def set_channel_active(
    channel_id: str, payload: ActiveRequest, scope: ScopeDep
) -> None:
    if not await scope.required_channels.set_active(channel_id, active=payload.active):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such channel.")


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WRITE])
async def remove_channel(channel_id: str, scope: ScopeDep) -> None:
    """A real delete, unlike the catalogue's.

    Nothing references a join requirement afterwards - it is a rule that
    applied while it existed, and no invoice names it.
    """
    if not await scope.required_channels.remove(channel_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such channel.")


def reject_unreachable(payload: NewChannel) -> None:
    """A private channel with no invite link is a door with no handle.

    The customer would be told to join something the bot cannot give them a
    button for, and the only way out of the gate would be to already be a
    member. Refused at the edge, where the operator can still fix it.
    """
    if not payload.chat_ref.startswith("@") and not payload.invite_url:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "برای کانال خصوصی، لینک دعوت لازم است؛ وگرنه کاربر راهی برای"
                " عضو شدن ندارد."
            ),
        )
    if payload.invite_url and not re.match(r"^https://t\.me/", payload.invite_url):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="لینک دعوت باید با https://t.me/ شروع شود.",
        )


#: Public because the reseller router applies the same rule to their own
#: channels. One definition, so the two surfaces cannot disagree about what
#: counts as a channel a customer can actually reach.
__all__ = ["CHAT_REF", "NewChannel", "reject_unreachable", "router"]
