"""The Android app's HTTP surface: sign-in, and Mini App routes over Bearer.

Persistence underneath is the permanently empty `FakeAsyncSession`, so these
assert what the wire looks like and what is refused. The state machine itself
is covered by `tests/unit/identity/test_app_link_login.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.config.settings import get_settings
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.api.app import create_app
from geekvpn.presentation.api.security import get_scope
from tests.conftest import TEST_BOT_TOKEN, build_test_container
from tests.fakes import FrozenClock, InMemoryUserRepository, RecordingAudit

pytestmark = pytest.mark.integration

START = "/api/app/auth/link/start"
POLL = "/api/app/auth/link/poll"
PASSWORD = "/api/app/auth/password"
DEVICE = {"deviceId": "d3a1", "deviceName": "Pixel 6", "platform": "android", "appVersion": "0.1.0"}


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def api_with_bot(monkeypatch: pytest.MonkeyPatch, settings) -> Iterator[TestClient]:
    monkeypatch.setenv("TELEGRAM__BOT_USERNAME", "@GeekVPNBot")
    get_settings.cache_clear()
    container = build_test_container(get_settings())
    with TestClient(create_app(container=container), raise_server_exceptions=False) as client:
        yield client


# -- sign-in -------------------------------------------------------------------


def test_start_answers_503_until_the_bot_username_is_configured(api: TestClient) -> None:
    response = api.post(START, json=DEVICE)
    assert response.status_code == 503


def test_start_returns_a_deep_link_and_a_poll_token(api_with_bot: TestClient) -> None:
    response = api_with_bot.post(START, json=DEVICE)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"requestId", "pollToken", "deepLink", "expiresIn"}
    assert body["deepLink"].startswith("https://t.me/GeekVPNBot?start=applogin_")
    # Telegram accepts at most 64 characters of [A-Za-z0-9_-] as a start parameter.
    start_param = body["deepLink"].split("start=", 1)[1]
    assert len(start_param) <= 64
    assert start_param.replace("_", "").replace("-", "").isalnum()
    assert body["expiresIn"] == 300
    # The code in the link and the poll token are different secrets.
    assert body["pollToken"] not in body["deepLink"]


def test_start_requires_a_device_id(api_with_bot: TestClient) -> None:
    response = api_with_bot.post(START, json={**DEVICE, "deviceId": ""})
    assert response.status_code == 422


def test_start_refuses_unknown_fields(api_with_bot: TestClient) -> None:
    response = api_with_bot.post(START, json={**DEVICE, "telegramId": 1})
    assert response.status_code == 422


def test_polling_an_unknown_token_is_a_404(api: TestClient) -> None:
    response = api.post(POLL, json={"pollToken": "x" * 43, "wait": False})
    assert response.status_code == 404


def test_a_password_login_for_an_unknown_username_is_a_plain_401(api: TestClient) -> None:
    response = api.post(
        PASSWORD,
        json={"username": "nobody_here", "password": "x" * 12, "deviceName": "Pixel 6"},
    )

    assert response.status_code == 401
    assert response.json()["title"] == "invalid_credentials"


def test_a_password_login_refuses_unknown_fields(api: TestClient) -> None:
    response = api.post(
        PASSWORD, json={"username": "ali_92", "password": "x" * 12, "telegramId": 1}
    )
    assert response.status_code == 422


# -- Mini App routes accept both schemes ----------------------------------------


def _signed_init_data(telegram_id: int) -> str:
    fields = {
        "user": json.dumps({"id": telegram_id, "first_name": "Amir"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "AAF",
    }
    secret = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class _Scope:
    """Only what the Mini App's authentication dependency reads."""

    def __init__(self, container: Container, users: InMemoryUserRepository) -> None:
        assert container.telegram_auth is not None
        self.authenticate_telegram = AuthenticateTelegramUser(
            users=users,
            verifier=container.telegram_auth,
            sessions=None,  # type: ignore[arg-type] - verification never issues tokens
            clock=FrozenClock(),
            audit=RecordingAudit(),
        )


@pytest.fixture
def customer_world(app: FastAPI, container: Container) -> Iterator[tuple[TestClient, User]]:
    users = InMemoryUserRepository()
    user = User.register(user_id=uuid.uuid4(), telegram_id=555, referral_code="R555")
    users.items[user.id] = user
    app.dependency_overrides[get_scope] = lambda: _Scope(container, users)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, user
    app.dependency_overrides.clear()


def _bearer(
    container: Container, *, subject_id: uuid.UUID, session_id: uuid.UUID
) -> dict[str, str]:
    token = container.access_tokens.issue(
        subject_type=SubjectType.USER, subject_id=subject_id, session_id=session_id
    ).value
    return {"Authorization": f"Bearer {token}"}


def test_the_same_miniapp_route_serves_initdata_and_a_bearer_token(
    customer_world: tuple[TestClient, User], container: Container
) -> None:
    client, user = customer_world

    with_init_data = client.get(
        "/api/miniapp/faq", headers={"Authorization": f"tma {_signed_init_data(555)}"}
    )
    with_bearer = client.get(
        "/api/miniapp/faq",
        headers=_bearer(container, subject_id=user.id, session_id=uuid.uuid4()),
    )

    assert with_init_data.status_code == 200
    assert with_bearer.status_code == 200
    assert with_bearer.json() == with_init_data.json()


def test_an_admin_token_is_refused_on_miniapp_routes(
    customer_world: tuple[TestClient, User], container: Container
) -> None:
    client, _ = customer_world
    token = container.access_tokens.issue(
        subject_type=SubjectType.ADMIN, subject_id=uuid.uuid4(), session_id=uuid.uuid4()
    ).value

    response = client.get("/api/miniapp/faq", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_a_logged_out_session_is_refused_at_once(
    customer_world: tuple[TestClient, User], container: Container
) -> None:
    client, user = customer_world
    session_id = uuid.uuid4()
    headers = _bearer(container, subject_id=user.id, session_id=session_id)
    assert client.get("/api/miniapp/faq", headers=headers).status_code == 200

    await container.revocations.revoke_session(session_id, ttl_seconds=60)

    assert client.get("/api/miniapp/faq", headers=headers).status_code == 401


def test_a_suspended_customer_is_refused_with_a_still_valid_token(
    customer_world: tuple[TestClient, User], container: Container
) -> None:
    client, user = customer_world
    user.suspend(reason="abuse")

    response = client.get(
        "/api/miniapp/faq",
        headers=_bearer(container, subject_id=user.id, session_id=uuid.uuid4()),
    )

    assert response.status_code in (401, 403)


def test_a_token_for_an_account_that_no_longer_exists_is_refused(
    customer_world: tuple[TestClient, User], container: Container
) -> None:
    client, _ = customer_world
    response = client.get(
        "/api/miniapp/faq",
        headers=_bearer(container, subject_id=uuid.uuid4(), session_id=uuid.uuid4()),
    )
    assert response.status_code == 401


# -- the routes the app calls exist ----------------------------------------------

#: Every call the Android app makes (com.geekvpn.api in GeekVPN-Android). A
#: route renamed or removed here breaks shipped phones, so it fails this test
#: instead of failing in the field.
APP_CALLS = [
    ("POST", "/api/app/auth/link/start"),
    ("POST", "/api/app/auth/link/poll"),
    ("POST", "/api/app/auth/password"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/sessions"),
    ("GET", "/api/miniapp/profile"),
    ("GET", "/api/miniapp/subscriptions"),
    ("GET", "/api/miniapp/storefront"),
    ("POST", "/api/miniapp/quote"),
    ("POST", "/api/miniapp/coupon/preview"),
    ("GET", "/api/miniapp/payment-methods"),
    ("POST", "/api/miniapp/checkout/wallet"),
    ("POST", "/api/miniapp/checkout/card"),
    ("POST", "/api/miniapp/checkout/gateway"),
    ("POST", "/api/miniapp/checkout/crypto"),
    ("POST", "/api/miniapp/payments/{payment_id}/receipt"),
    ("POST", "/api/miniapp/payments/{payment_id}/receipt-photo"),
    ("GET", "/api/miniapp/payments/pending"),
    ("GET", "/api/miniapp/trial"),
    ("POST", "/api/miniapp/trial"),
    ("GET", "/api/miniapp/wallet"),
    ("GET", "/api/miniapp/wallet/transactions"),
    ("POST", "/api/miniapp/wallet/topup"),
    ("GET", "/api/miniapp/referral"),
    ("GET", "/api/miniapp/tickets"),
    ("POST", "/api/miniapp/tickets"),
    ("GET", "/api/miniapp/tickets/{ticket_id}/messages"),
    ("POST", "/api/miniapp/tickets/{ticket_id}/messages"),
    ("GET", "/api/miniapp/servers"),
    ("GET", "/api/miniapp/faq"),
]


def test_every_route_the_app_calls_is_registered(app: FastAPI) -> None:
    # From the schema rather than `app.routes`: included routers are wrapped,
    # and the schema is what a client is actually promised.
    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    missing = [call for call in APP_CALLS if call not in registered]
    assert not missing, missing
