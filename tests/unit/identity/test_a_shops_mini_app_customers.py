"""The Mini App opened from a reseller's bot.

Their bot's initData is signed with *their* token, and their customer is a
separate person from the same Telegram account in our own bot. The header
only names the shop; the signature has to prove it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from tests.fakes import FrozenClock, InMemoryUserRepository, RecordingAudit

from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.application.resellers.tenant_bots import shop_mini_app_url
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.infrastructure.security.telegram import TelegramSignatureVerifier
from geekvpn.presentation.api.miniapp_security import _shop_user

pytestmark = pytest.mark.unit

PLATFORM_TOKEN = "100:platform-token"
SHOP_TOKEN = "200:shop-token"
SHOP = uuid.uuid4()


def _init_data(token: str, telegram_id: int = 4242) -> str:
    fields = {
        "user": json.dumps({"id": telegram_id, "first_name": "Sara"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "AAF",
    }
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class _Resellers:
    def __init__(
        self, status: ResellerStatus = ResellerStatus.ACTIVE, token: str | None = SHOP_TOKEN
    ) -> None:
        self.shop = SimpleNamespace(id=SHOP, status=status, brand_fa="شمال", name_fa="شمال")
        self.token = token

    async def get(self, reseller_id: uuid.UUID):
        return self.shop if reseller_id == SHOP else None

    async def bot_token(self, reseller_id: uuid.UUID) -> str | None:
        return self.token if reseller_id == SHOP else None

    async def texts(self, reseller_id: uuid.UUID) -> dict[str, str]:
        return {}


def _scope(resellers: _Resellers | None = None) -> SimpleNamespace:
    users = InMemoryUserRepository()
    return SimpleNamespace(
        users=users,
        resellers=resellers or _Resellers(),
        reseller=None,
        reseller_texts=None,
        authenticate_telegram=AuthenticateTelegramUser(
            users=users,
            verifier=TelegramSignatureVerifier(bot_token=PLATFORM_TOKEN),
            sessions=None,  # type: ignore[arg-type] - verification issues no tokens
            clock=FrozenClock(),
            audit=RecordingAudit(),
        ),
    )


async def test_the_shops_own_signature_signs_in_the_shops_customer() -> None:
    scope = _scope()

    user = await _shop_user(_init_data(SHOP_TOKEN), SHOP.hex, scope=scope, container=None)

    assert user.telegram_id == 4242
    # The shop is on the scope: prices, payment methods and orders read it.
    assert scope.reseller is scope.resellers.shop


async def test_naming_a_shop_with_our_signature_is_refused() -> None:
    """A customer of our bot cannot become a shop's customer by adding a header."""
    with pytest.raises(DomainError):
        await _shop_user(_init_data(PLATFORM_TOKEN), SHOP.hex, scope=_scope(), container=None)


async def test_a_closed_shop_or_one_without_a_bot_signs_nobody_in() -> None:
    for resellers in (_Resellers(status=ResellerStatus.CLOSED), _Resellers(token=None)):
        with pytest.raises(DomainError):
            await _shop_user(
                _init_data(SHOP_TOKEN), SHOP.hex, scope=_scope(resellers), container=None
            )


async def test_an_unknown_or_malformed_shop_is_refused() -> None:
    for shop in (uuid.uuid4().hex, "not-a-shop"):
        with pytest.raises(DomainError):
            await _shop_user(_init_data(SHOP_TOKEN), shop, scope=_scope(), container=None)


async def test_the_same_telegram_account_is_a_separate_customer_in_the_shop() -> None:
    scope = _scope()
    ours = await scope.authenticate_telegram.verify_mini_app_request(_init_data(PLATFORM_TOKEN))
    theirs = await _shop_user(_init_data(SHOP_TOKEN), SHOP.hex, scope=scope, container=None)

    assert ours.telegram_id == theirs.telegram_id
    assert ours.id != theirs.id


def test_the_shops_button_opens_the_app_marked_with_the_shop() -> None:
    assert (
        shop_mini_app_url("https://app.example/", SHOP) == f"https://app.example/?shop={SHOP.hex}"
    )
    # An address that already carries a query keeps it, and a stale shop is replaced.
    assert shop_mini_app_url("https://app.example/?v=2&shop=old", SHOP) == (
        f"https://app.example/?v=2&shop={SHOP.hex}"
    )
