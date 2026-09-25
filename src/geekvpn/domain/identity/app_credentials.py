"""A customer's username and password for the Android app.

Telegram is how customers sign in everywhere else, and the app's first way in
is approving it inside the bot. Some people would rather type a password - a
phone without Telegram, a family member's phone - so a customer can set one
from the bot's profile screen. It is an extra key to the same account, never
a separate account.

Kept apart from `User` on purpose: the user row is the Telegram identity and
is rewritten from Telegram's payload on every authentication; a password hash
has no business riding along in that write.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from geekvpn.domain.identity.errors import AppPasswordWeakError, AppUsernameInvalidError

USERNAME_MIN = 4
USERNAME_MAX = 32
PASSWORD_MIN = 8
#: Argon2 accepts anything, but a 10 MB "password" is a way to burn CPU.
PASSWORD_MAX = 128

_USERNAME = re.compile(rf"[a-z][a-z0-9_]{{{USERNAME_MIN - 1},{USERNAME_MAX - 1}}}")


@dataclass(frozen=True, slots=True)
class AppCredential:
    user_id: uuid.UUID
    #: Lower case, as `normalize_username` returns it. Unique across customers.
    username: str
    password_hash: str
    updated_at: datetime


def normalize_username(raw: str) -> str:
    """Lower-case and validate. `Ali_1` and `ali_1` are the same login.

    Latin only: a Persian or mixed-script username invites look-alikes
    (`ی` and `ي`, zero-width joiners) that a customer cannot tell apart when
    typing it back on a phone keyboard.
    """
    username = raw.strip().lower()
    if not _USERNAME.fullmatch(username):
        raise AppUsernameInvalidError()
    return username


def check_password(password: str, *, username: str) -> None:
    """Length only, plus "not the username".

    No composition rules: they push people to `Password1!`. Length is what
    makes a password expensive to guess, and the login is rate limited.
    """
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise AppPasswordWeakError()
    if password.strip().lower() == username:
        raise AppPasswordWeakError()
