"""Telegram has two spellings of the data-check string, and sends both.

The documented rule is "every field except `hash`". Then `signature` arrived
for third-party Ed25519 validation and the ecosystem split: some clients hash
over it, some exclude it. A Mini App that verified last month can stop
verifying after a client update, with no error to read - just a hash that does
not match, which is indistinguishable from a wrong bot token.

Accepting either costs nothing: both are HMACs over a well-defined string keyed
with the bot token, so a match still proves Telegram signed this payload for
this bot.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from geekvpn.domain.identity.errors import InvalidTelegramAuthError
from geekvpn.infrastructure.security.telegram import TelegramSignatureVerifier

pytestmark = pytest.mark.unit

TOKEN = "7556665256:AAH-fake-token-for-tests"
USER = {"id": 87791922, "first_name": "امیر"}


def _sign(fields: dict[str, str], *, over_signature: bool) -> str:
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    excluded = {"hash"} if over_signature else {"hash", "signature"}
    check = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items()) if key not in excluded
    )
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def _init_data(*, over_signature: bool, with_signature: bool = True) -> str:
    fields = {
        "user": json.dumps(USER, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "AAF",
    }
    if with_signature:
        fields["signature"] = "some-ed25519-signature"
    fields["hash"] = _sign(fields, over_signature=over_signature)
    return urlencode(fields)


@pytest.fixture
def verifier() -> TelegramSignatureVerifier:
    return TelegramSignatureVerifier(bot_token=TOKEN)


def test_a_client_that_excludes_signature_is_accepted(verifier) -> None:
    identity = verifier.verify_mini_app(_init_data(over_signature=False))

    assert identity.telegram_id == USER["id"]


def test_a_client_that_hashes_over_signature_is_accepted(verifier) -> None:
    """The spelling that broke a working Mini App."""
    identity = verifier.verify_mini_app(_init_data(over_signature=True))

    assert identity.telegram_id == USER["id"]


def test_payloads_without_a_signature_field_still_verify(verifier) -> None:
    """Older clients, and the Login Widget's cousin."""
    identity = verifier.verify_mini_app(_init_data(over_signature=True, with_signature=False))

    assert identity.telegram_id == USER["id"]


def test_a_forged_hash_is_still_refused(verifier) -> None:
    """Accepting two spellings must not mean accepting anything."""
    forged = _init_data(over_signature=False).replace("hash=", "hash=00")

    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app(forged)


def test_another_bots_token_is_still_refused() -> None:
    other = TelegramSignatureVerifier(bot_token="1234:different")

    with pytest.raises(InvalidTelegramAuthError):
        other.verify_mini_app(_init_data(over_signature=False))
