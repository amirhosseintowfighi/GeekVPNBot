"""Telegram signature verification.

Fixtures are generated with the real algorithm rather than hard-coded, so these
tests fail loudly if the derivation ever changes - which is exactly the bug
class they exist to catch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from geekvpn.domain.identity.enums import AuthMethod
from geekvpn.domain.identity.errors import InvalidTelegramAuthError
from geekvpn.infrastructure.security.telegram import TelegramSignatureVerifier

BOT_TOKEN = "123456:AAHtesttokenfortestingonly"


def build_init_data(**overrides) -> str:
    user = overrides.pop(
        "user",
        {
            "id": 987654321,
            "first_name": "Amir",
            "username": "amir",
            "language_code": "fa",
            "is_premium": True,
        },
    )
    fields = {
        "query_id": "AAF",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(int(time.time())),
    }
    fields.update({k: str(v) for k, v in overrides.items()})

    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def build_widget_payload(**overrides) -> dict[str, str]:
    fields = {
        "id": "987654321",
        "first_name": "Amir",
        "username": "amir",
        "auth_date": str(int(time.time())),
    }
    fields.update({k: str(v) for k, v in overrides.items()})
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return fields


@pytest.fixture
def verifier():
    return TelegramSignatureVerifier(bot_token=BOT_TOKEN)


def test_valid_mini_app_init_data_is_accepted(verifier):
    identity = verifier.verify_mini_app(build_init_data())

    assert identity.telegram_id == 987654321
    assert identity.username == "amir"
    assert identity.language_code == "fa"
    assert identity.is_premium is True
    assert identity.method is AuthMethod.TELEGRAM_MINI_APP


def test_start_param_is_carried_through(verifier):
    identity = verifier.verify_mini_app(build_init_data(start_param="ref_ABC123"))
    assert identity.start_param == "ref_ABC123"


def test_a_tampered_field_invalidates_the_signature(verifier):
    tampered = build_init_data().replace("987654321", "111111111")
    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app(tampered)


def test_a_different_bot_token_cannot_verify():
    other = TelegramSignatureVerifier(bot_token="999:other")
    with pytest.raises(InvalidTelegramAuthError):
        other.verify_mini_app(build_init_data())


def test_stale_init_data_is_rejected(verifier):
    """Without a freshness window, one leaked initData is a permanent password."""
    old = build_init_data(auth_date=str(int(time.time()) - 200000))
    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app(old)


def test_a_far_future_auth_date_is_rejected(verifier):
    future = build_init_data(auth_date=str(int(time.time()) + 5000))
    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app(future)


def test_missing_hash_is_rejected(verifier):
    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app("user=%7B%7D&auth_date=1")


def test_empty_init_data_is_rejected(verifier):
    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app("")


def test_the_signature_field_is_excluded_from_the_check_string(verifier):
    """Telegram's newer Ed25519 `signature` field is not part of the HMAC."""
    identity = verifier.verify_mini_app(build_init_data() + "&signature=abcdef")
    assert identity.telegram_id == 987654321


def test_valid_login_widget_payload_is_accepted(verifier):
    identity = verifier.verify_login_widget(build_widget_payload())
    assert identity.telegram_id == 987654321
    assert identity.method is AuthMethod.TELEGRAM_LOGIN_WIDGET


def test_widget_and_mini_app_secrets_are_not_interchangeable(verifier):
    """The classic Telegram auth bug: using SHA256(token) for both schemes."""
    with pytest.raises(InvalidTelegramAuthError):
        verifier.verify_mini_app(urlencode(build_widget_payload()))
