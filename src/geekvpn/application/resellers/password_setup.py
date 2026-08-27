"""Choosing a first password without one ever having been sent.

An approved reseller needs a panel login. The obvious way - generate a password
and message it - puts a live credential in somebody's Telegram history forever,
readable by anyone who ever picks up their phone.

So the approval issues a one-time token instead. It goes into a link, the link
opens a page, and the person types a password only they have seen. What is
stored is a hash, like any password, so a database dump hands nobody an
account; and it is cleared the moment it is spent, so a link forwarded by
accident works once and then does not.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Protocol

from geekvpn.application.resellers.ports import Clock

#: Matches what `ManageAdmins` enforces when an operator changes a password.
#: Stated here as well because this path never goes through that method - the
#: person has no current password to prove.
MIN_PASSWORD_LENGTH = 12


class InvalidSetupToken(Exception):
    """Wrong, expired, already used, or for an account that is gone.

    One error for all four on purpose. Telling somebody which of them applies
    tells an attacker which admin ids exist and which have a pending link.
    """


class TokenStore(Protocol):
    async def find(self, admin_id: uuid.UUID) -> tuple[str, datetime] | None: ...

    async def clear(self, admin_id: uuid.UUID) -> None: ...


class AdminPasswords(Protocol):
    async def get(self, admin_id: uuid.UUID) -> Any | None: ...

    async def update(self, admin: Any) -> None: ...


class PasswordSetup:
    def __init__(
        self,
        *,
        tokens: TokenStore,
        admins: AdminPasswords,
        hasher: Any,
        clock: Clock,
    ) -> None:
        self._tokens = tokens
        self._admins = admins
        self._hasher = hasher
        self._clock = clock

    async def redeem(self, admin_id: uuid.UUID, *, token: str, password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )

        issued = await self._tokens.find(admin_id)
        if issued is None:
            raise InvalidSetupToken("That link is not valid.")

        token_hash, expires_at = issued
        now = self._clock.now()
        if now >= expires_at or not self._hasher.verify(token, token_hash):
            # Cleared on an expiry, kept on a wrong value. An expired token is
            # dead anyway and leaving it invites a second attempt against it; a
            # wrong guess must not let somebody burn the real owner's link.
            if now >= expires_at:
                await self._tokens.clear(admin_id)
            raise InvalidSetupToken("That link is not valid.")

        admin = await self._admins.get(admin_id)
        if admin is None:
            raise InvalidSetupToken("That link is not valid.")

        admin.set_password_hash(self._hasher.hash(password), now=now)
        await self._admins.update(admin)
        # Spent. A link that still worked after the password was set would be a
        # standing way to take the account over.
        await self._tokens.clear(admin_id)


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "AdminPasswords",
    "InvalidSetupToken",
    "PasswordSetup",
    "TokenStore",
]
