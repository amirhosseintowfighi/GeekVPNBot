"""Telegram signature verification.

Two different schemes, both HMAC-SHA256, with one critical difference in how
the key is derived:

* **Mini App `initData`**: `secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`
* **Login Widget**:       `secret = SHA256(bot_token)`

Getting these backwards is the classic Telegram auth bug, and the failure mode
is silent: everything looks fine because you are still checking *a* signature.

Both verifications:
1. build the data-check string as `key=value` lines sorted by key, joined by
   `\n`, excluding `hash` (and `signature`, which is Telegram's newer Ed25519
   field for third-party validation and is not part of the HMAC input);
2. compare with `hmac.compare_digest`, never `==`;
3. reject stale `auth_date`, because a valid signature is valid forever -
   without a freshness window, one leaked `initData` string is a permanent
   credential.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from geekvpn.application.ports.telegram_auth import TelegramIdentity
from geekvpn.domain.identity.enums import AuthMethod
from geekvpn.domain.identity.errors import InvalidTelegramAuthError
from geekvpn.infrastructure.logging.setup import get_logger

#: How old signed Telegram data may be. Telegram itself recommends checking
#: this; 24h matches how long a Mini App session realistically stays open.
logger = get_logger(__name__)

DEFAULT_MAX_AGE_SECONDS = 86_400

_EXCLUDED_FROM_CHECK_STRING = frozenset({"hash", "signature"})


class TelegramSignatureVerifier:
    def __init__(
        self,
        *,
        bot_token: str,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        if not bot_token:
            raise ValueError("A bot token is required to verify Telegram auth data.")
        self._bot_token = bot_token
        self._max_age = max_age_seconds
        # Derived once: HMAC key derivation on every request is wasted work.
        self._mini_app_secret = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        self._widget_secret = hashlib.sha256(bot_token.encode("utf-8")).digest()

    # -- Mini App ----------------------------------------------------------

    def verify_mini_app(
        self, init_data: str, *, max_age_seconds: int | None = None
    ) -> TelegramIdentity:
        if not init_data:
            raise InvalidTelegramAuthError("Empty initData.")

        try:
            fields = dict(parse_qsl(init_data, strict_parsing=True, keep_blank_values=True))
        except ValueError as exc:
            raise InvalidTelegramAuthError("Malformed initData.") from exc

        provided = fields.get("hash")
        if not provided:
            raise InvalidTelegramAuthError("initData has no hash.")

        if not self._signature_matches(fields, provided):
            # The field names, never the values: they say whether `signature`
            # was even present, which is the difference between "Telegram
            # changed the payload again" and "this is not our bot's token".
            logger.info(
                "telegram.mini_app_hash_mismatch",
                fields=sorted(key for key in fields if key != "hash"),
            )
            raise InvalidTelegramAuthError()

        self._ensure_fresh(fields.get("auth_date"), max_age_seconds)

        raw_user = fields.get("user")
        if not raw_user:
            raise InvalidTelegramAuthError("initData has no user object.")
        try:
            user: dict[str, Any] = json.loads(raw_user)
        except json.JSONDecodeError as exc:
            raise InvalidTelegramAuthError("initData user is not valid JSON.") from exc

        return _identity_from(
            user,
            method=AuthMethod.TELEGRAM_MINI_APP,
            start_param=fields.get("start_param"),
        )

    # -- Login Widget ------------------------------------------------------

    def verify_login_widget(self, payload: dict[str, str]) -> TelegramIdentity:
        fields = {key: str(value) for key, value in payload.items() if value is not None}
        provided = fields.get("hash")
        if not provided:
            raise InvalidTelegramAuthError("Login payload has no hash.")

        expected = hmac.new(
            key=self._widget_secret,
            msg=_data_check_string(fields).encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, provided):
            raise InvalidTelegramAuthError()

        self._ensure_fresh(fields.get("auth_date"))

        try:
            telegram_id = int(fields["id"])
        except (KeyError, ValueError) as exc:
            raise InvalidTelegramAuthError("Login payload has no valid id.") from exc

        return TelegramIdentity(
            telegram_id=telegram_id,
            method=AuthMethod.TELEGRAM_LOGIN_WIDGET,
            username=fields.get("username"),
            first_name=fields.get("first_name"),
            last_name=fields.get("last_name"),
            photo_url=fields.get("photo_url"),
        )

    # -- shared ------------------------------------------------------------

    def _ensure_fresh(self, auth_date: str | None, max_age_seconds: int | None = None) -> None:
        if auth_date is None:
            raise InvalidTelegramAuthError("Missing auth_date.")
        try:
            issued_at = int(auth_date)
        except ValueError as exc:
            raise InvalidTelegramAuthError("Malformed auth_date.") from exc

        age = int(time.time()) - issued_at
        # A negative age beyond small clock skew means a forged future date.
        if age < -60 or age > (max_age_seconds if max_age_seconds is not None else self._max_age):
            raise InvalidTelegramAuthError("Telegram authentication data has expired.")


    def _signature_matches(self, fields: dict[str, str], provided: str) -> bool:
        """Both spellings of the data-check string, because Telegram has two.

        The documented rule is "every field except `hash`". Then `signature`
        arrived for third-party Ed25519 validation, and the ecosystem split:
        some clients hash over it, some exclude it, and Telegram's own docs
        have said both at different times. A Mini App that verified last month
        can stop verifying after a client update, with no error but a hash that
        does not match - which is exactly what this looked like.

        Accepting either costs nothing in security. Both are HMACs over a
        well-defined string keyed with the bot token, so a valid one still
        proves Telegram signed this payload for this bot. What excluding
        `signature` permits is tampering with `signature` itself, which nothing
        here reads: the Ed25519 path is for third parties who do not have the
        bot token, and we do.
        """
        for excluded in (_EXCLUDED_FROM_CHECK_STRING, frozenset({"hash"})):
            expected = hmac.new(
                key=self._mini_app_secret,
                msg=_data_check_string(fields, excluded).encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(expected, provided):
                return True
        return False


def _data_check_string(
    fields: dict[str, str], excluded: frozenset[str] = _EXCLUDED_FROM_CHECK_STRING
) -> str:
    return "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items()) if key not in excluded
    )


def _identity_from(
    user: dict[str, Any], *, method: AuthMethod, start_param: str | None
) -> TelegramIdentity:
    try:
        telegram_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTelegramAuthError("initData user has no valid id.") from exc

    return TelegramIdentity(
        telegram_id=telegram_id,
        method=method,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        language_code=user.get("language_code"),
        photo_url=user.get("photo_url"),
        is_premium=bool(user.get("is_premium", False)),
        start_param=start_param,
    )
