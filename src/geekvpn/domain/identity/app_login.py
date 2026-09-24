"""A request from the Android app to be signed in, approved inside the bot.

The app has no Telegram signature of its own to present, so the proof comes
from the bot: the app asks for a request, opens a `t.me` deep link carrying a
one-time code, and the customer taps "approve" in a chat Telegram has already
authenticated. The app then collects its tokens with a poll token only it
holds.

Two secrets, and only their hashes are stored. The code travels through
Telegram and the customer's hands (it is in a link); the poll token never
leaves the app. Knowing one is useless without the other.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime


class AppLoginStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class AppLoginRequest:
    id: uuid.UUID
    code_hash: str
    poll_token_hash: str
    device_id: str
    device_name: str
    platform: str
    app_version: str
    ip: str | None
    status: AppLoginStatus
    created_at: datetime
    expires_at: datetime
    #: Set once, by the first Telegram account to open the link. Only that
    #: account may then approve or deny.
    telegram_user_id: int | None = None

    def status_at(self, now: datetime) -> AppLoginStatus:
        """The status a reader should act on.

        Expiry is not a write: a request nobody touches again simply reads as
        expired once its time is up. An approval that the app never came back
        for expires the same way, so a stale approval cannot be redeemed hours
        later by whoever finds the poll token.
        """
        if self.status in (AppLoginStatus.PENDING, AppLoginStatus.APPROVED) and (
            now >= self.expires_at
        ):
            return AppLoginStatus.EXPIRED
        return self.status
