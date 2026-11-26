"""The bot's owner controls, through `/api/miniapp/*`, for the Android app.

Signed-in devices, a service's name, handing a service to someone else, and
returning an unused one. The routes sit on the real `BotServiceOwnership`
(see `tests/unit/bot/ownership_fakes.py`), so a rule the bot enforces is
enforced here by the same code; these pin the wire on top of it: status codes,
the problem's `title` and `message_fa`, camelCase fields, and that another
customer's service or device is a 404.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.application.bot.read_models import SubscriptionCard
from geekvpn.application.identity.app_link_login import AppDevice
from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.application.platform.settings_service import (
    REFUND_WINDOW_HOURS,
    RENAME_ENABLED,
    TRANSFER_ENABLED,
)
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.user import User
from geekvpn.infrastructure.bot.readers import to_card
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.api.miniapp_security import mini_app_services
from geekvpn.presentation.api.security import get_scope
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.fa import toman
from tests.fakes import FrozenClock, InMemoryUserRepository, RecordingAudit
from tests.unit.bot.ownership_fakes import FRIEND_TG, OWNER_TG, World

pytestmark = pytest.mark.integration

MINIAPP = "/api/miniapp"


@dataclass
class FakeDevices:
    """`AppLinkLogin`'s device half. Its rules are in `test_app_link_login.py`."""

    owned: dict[uuid.UUID, list[AppDevice]] = field(default_factory=dict)
    disconnected: list[uuid.UUID] = field(default_factory=list)

    async def devices(self, user_id: uuid.UUID) -> list[AppDevice]:
        return list(self.owned.get(user_id, []))

    async def disconnect(self, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
        mine = self.owned.get(user_id, [])
        for device in mine:
            if device.session_id == session_id:
                mine.remove(device)
                self.disconnected.append(session_id)
                return True
        return False


class _Cards:
    """`GET /subscriptions`' reader, over the same rows the ownership adapter edits."""

    def __init__(self, world: World, users: InMemoryUserRepository) -> None:
        self._world = world
        self._users = users

    async def list_for_user(self, user_id: uuid.UUID) -> list[SubscriptionCard]:
        user = self._users.items[user_id]
        rows = await self._world.subscriptions.list_for_user(user.telegram_id)
        return [to_card(row, None, category_name_fa="اروپا") for row in rows]


@dataclass
class Api:
    client: TestClient
    world: World
    devices: FakeDevices
    owner: dict[str, str]
    friend: dict[str, str]
    owner_session: uuid.UUID

    def url(self, tail: str = "") -> str:
        return f"{MINIAPP}/subscriptions/{self.world.sub_id}{tail}"


def _token(container: Container, user: User, session_id: uuid.UUID) -> dict[str, str]:
    token = container.access_tokens.issue(
        subject_type=SubjectType.USER, subject_id=user.id, session_id=session_id
    ).value
    return {"Authorization": f"Bearer {token}"}


def _build(app: FastAPI, container: Container, settings: dict[str, Any]) -> Iterator[Api]:
    world = World(settings=settings)
    users = InMemoryUserRepository()
    users.items[world.owner.id] = world.owner
    users.items[world.friend.id] = world.friend
    assert container.telegram_auth is not None
    devices = FakeDevices()
    scope = SimpleNamespace(
        authenticate_telegram=AuthenticateTelegramUser(
            users=users,
            verifier=container.telegram_auth,
            sessions=None,  # type: ignore[arg-type] - verification never issues tokens
            clock=FrozenClock(),
            audit=RecordingAudit(),
        ),
        app_link_login=devices,
    )
    services = SimpleNamespace(ownership=world.ownership, subscriptions=_Cards(world, users))
    app.dependency_overrides[get_scope] = lambda: scope
    app.dependency_overrides[mini_app_services] = lambda: services
    owner_session = uuid.uuid4()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Api(
            client=client,
            world=world,
            devices=devices,
            owner=_token(container, world.owner, owner_session),
            friend=_token(container, world.friend, uuid.uuid4()),
            owner_session=owner_session,
        )
    app.dependency_overrides.clear()


@pytest.fixture
def api(app: FastAPI, container: Container) -> Iterator[Api]:
    yield from _build(app, container, {REFUND_WINDOW_HOURS.key: 24})


@pytest.fixture
def switched_off(app: FastAPI, container: Container) -> Iterator[Api]:
    yield from _build(
        app,
        container,
        {RENAME_ENABLED.key: False, TRANSFER_ENABLED.key: False, REFUND_WINDOW_HOURS.key: 0},
    )


def _problem(response: Any, status: int, title: str, message_fa: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["title"] == title
    if message_fa is not None:
        assert body["message_fa"] == message_fa
    else:
        assert any("؀" <= ch <= "ۿ" for ch in body["message_fa"])


# -- devices ---------------------------------------------------------------------


def _device(session_id: uuid.UUID, name: str, **extra: Any) -> AppDevice:
    when = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)
    return AppDevice(
        session_id=session_id,
        name=name,
        created_at=when,
        last_used_at=when + timedelta(days=1),
        **extra,
    )


def test_the_device_list_marks_the_device_asking(api: Api) -> None:
    other = uuid.uuid4()
    api.devices.owned[api.world.owner.id] = [
        _device(api.owner_session, "Pixel 7", platform="android", app_version="1.2.0"),
        _device(other, "Android"),
    ]

    response = api.client.get(f"{MINIAPP}/devices", headers=api.owner)

    assert response.status_code == 200
    assert response.json() == [
        {
            "deviceId": str(api.owner_session),
            "name": "Pixel 7",
            "platform": "android",
            "appVersion": "1.2.0",
            "createdAt": "2026-11-20T09:30:00Z",
            "lastSeenAt": "2026-11-21T09:30:00Z",
            "current": True,
        },
        {
            "deviceId": str(other),
            "name": "Android",
            "platform": None,
            "appVersion": None,
            "createdAt": "2026-11-20T09:30:00Z",
            "lastSeenAt": "2026-11-21T09:30:00Z",
            "current": False,
        },
    ]


def test_no_devices_is_an_empty_list(api: Api) -> None:
    response = api.client.get(f"{MINIAPP}/devices", headers=api.owner)

    assert (response.status_code, response.json()) == (200, [])


def test_revoking_a_device_signs_it_out(api: Api) -> None:
    other = uuid.uuid4()
    api.devices.owned[api.world.owner.id] = [_device(other, "Pixel 6")]

    response = api.client.post(f"{MINIAPP}/devices/{other}/revoke", headers=api.owner)

    assert response.status_code == 204
    assert response.content == b""
    assert api.devices.disconnected == [other]


def test_a_device_may_sign_itself_out(api: Api) -> None:
    api.devices.owned[api.world.owner.id] = [_device(api.owner_session, "Pixel 7")]

    response = api.client.post(f"{MINIAPP}/devices/{api.owner_session}/revoke", headers=api.owner)

    assert response.status_code == 204
    assert api.devices.disconnected == [api.owner_session]


def test_someone_elses_device_is_a_404_and_stays_signed_in(api: Api) -> None:
    theirs = uuid.uuid4()
    api.devices.owned[api.world.owner.id] = [_device(theirs, "Pixel 7")]

    response = api.client.post(f"{MINIAPP}/devices/{theirs}/revoke", headers=api.friend)

    _problem(response, 404, "device_not_found", T.DEVICE_NOT_FOUND)
    assert api.devices.disconnected == []


@pytest.mark.parametrize("device_id", ["not-a-uuid", str(uuid.uuid4())])
def test_an_unknown_or_malformed_device_is_the_same_404(api: Api, device_id: str) -> None:
    response = api.client.post(f"{MINIAPP}/devices/{device_id}/revoke", headers=api.owner)

    _problem(response, 404, "device_not_found", T.DEVICE_NOT_FOUND)


# -- rename ----------------------------------------------------------------------


async def test_renaming_answers_the_card_with_the_new_name(api: Api) -> None:
    await api.world.service()

    response = api.client.post(api.url("/name"), json={"name": "گوشی من"}, headers=api.owner)

    assert response.status_code == 200
    card = response.json()
    assert card["subscriptionId"] == str(api.world.sub_id)
    assert card["displayName"] == "گوشی من"
    # The same card the list shows, not a thinner one.
    assert card["categoryNameFa"] == "اروپا"
    listed = api.client.get(f"{MINIAPP}/subscriptions", headers=api.owner).json()
    assert listed == [card]


@pytest.mark.parametrize("cleared", [None, "", "   ", "-"])
async def test_an_empty_name_goes_back_to_the_plans(api: Api, cleared: str | None) -> None:
    sub = await api.world.service()
    sub.rename("قبلی")

    response = api.client.post(api.url("/name"), json={"name": cleared}, headers=api.owner)

    assert response.status_code == 200
    assert response.json()["displayName"] is None


async def test_a_name_over_32_characters_is_refused(api: Api) -> None:
    await api.world.service()

    response = api.client.post(api.url("/name"), json={"name": "x" * 33}, headers=api.owner)

    _problem(response, 422, "service_name_too_long", T.RENAME_TOO_LONG)


async def test_renaming_someone_elses_service_is_a_404(api: Api) -> None:
    sub = await api.world.service()

    response = api.client.post(api.url("/name"), json={"name": "مال من"}, headers=api.friend)

    _problem(response, 404, "subscription_not_found")
    assert sub.display_name is None


async def test_renaming_a_revoked_service_is_refused(api: Api) -> None:
    sub = await api.world.service()
    sub.revoke(reason_fa="تست", at=datetime(2026, 11, 26, tzinfo=UTC))

    response = api.client.post(api.url("/name"), json={"name": "x"}, headers=api.owner)

    _problem(response, 409, "subscription_revoked")


async def test_renaming_when_the_shop_switched_it_off(switched_off: Api) -> None:
    await switched_off.world.service()

    response = switched_off.client.post(
        switched_off.url("/name"), json={"name": "x"}, headers=switched_off.owner
    )

    _problem(response, 409, "feature_disabled", T.FEATURE_OFF)


# -- transfer --------------------------------------------------------------------


async def test_a_transfer_moves_the_service_between_the_two_lists(api: Api) -> None:
    await api.world.service()

    response = api.client.post(
        api.url("/transfer"), json={"recipient": str(FRIEND_TG)}, headers=api.owner
    )

    assert response.status_code == 200
    assert response.json() == {
        "subscriptionId": str(api.world.sub_id),
        "recipientTelegramId": FRIEND_TG,
        "status": "done",
        "messageFa": T.TRANSFER_DONE,
    }
    assert api.client.get(f"{MINIAPP}/subscriptions", headers=api.owner).json() == []
    [theirs] = api.client.get(f"{MINIAPP}/subscriptions", headers=api.friend).json()
    assert theirs["subscriptionId"] == str(api.world.sub_id)
    # The recipient hears about it in Telegram, the operators get the report.
    assert api.world.sync.dispatched == [FRIEND_TG]
    assert api.world.sync.reports[-1].endswith("از طریق: اپ")


async def test_the_recipient_may_be_a_number_or_persian_digits(api: Api) -> None:
    await api.world.service()
    persian = str(FRIEND_TG).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    response = api.client.post(api.url("/transfer"), json={"recipient": persian}, headers=api.owner)

    assert response.status_code == 200
    assert response.json()["recipientTelegramId"] == FRIEND_TG


async def test_a_numeric_recipient_is_accepted_too(api: Api) -> None:
    await api.world.service()

    response = api.client.post(
        api.url("/transfer"), json={"recipient": FRIEND_TG}, headers=api.owner
    )

    assert response.status_code == 200


@pytest.mark.parametrize("recipient", ["@friend", "abc", "", "12 34"])
async def test_a_recipient_that_is_not_a_telegram_id_is_refused(api: Api, recipient: str) -> None:
    await api.world.service()

    response = api.client.post(
        api.url("/transfer"), json={"recipient": recipient}, headers=api.owner
    )

    _problem(response, 422, "transfer_recipient_invalid", T.TRANSFER_BAD_ID)


async def test_a_transfer_to_oneself_is_refused(api: Api) -> None:
    await api.world.service()

    response = api.client.post(
        api.url("/transfer"), json={"recipient": str(OWNER_TG)}, headers=api.owner
    )

    _problem(response, 422, "transfer_to_self", T.TRANSFER_SELF)


async def test_a_recipient_who_never_started_the_bot_is_refused(api: Api) -> None:
    sub = await api.world.service()

    response = api.client.post(api.url("/transfer"), json={"recipient": "31337"}, headers=api.owner)

    _problem(response, 422, "transfer_recipient_not_found", T.TRANSFER_NO_SUCH_USER)
    assert sub.user_id == OWNER_TG


async def test_giving_away_someone_elses_service_is_a_404(api: Api) -> None:
    sub = await api.world.service()

    response = api.client.post(
        api.url("/transfer"), json={"recipient": str(FRIEND_TG)}, headers=api.friend
    )

    _problem(response, 404, "subscription_not_found")
    assert sub.user_id == OWNER_TG


async def test_a_revoked_service_cannot_be_given_away(api: Api) -> None:
    sub = await api.world.service()
    sub.revoke(reason_fa="تست", at=datetime(2026, 11, 26, tzinfo=UTC))

    response = api.client.post(
        api.url("/transfer"), json={"recipient": str(FRIEND_TG)}, headers=api.owner
    )

    _problem(response, 409, "subscription_revoked")


async def test_transfers_when_the_shop_switched_them_off(switched_off: Api) -> None:
    await switched_off.world.service()

    response = switched_off.client.post(
        switched_off.url("/transfer"),
        json={"recipient": str(FRIEND_TG)},
        headers=switched_off.owner,
    )

    _problem(response, 409, "feature_disabled", T.FEATURE_OFF)


# -- refund ----------------------------------------------------------------------


async def test_an_unused_service_is_offered_back_for_its_price(api: Api) -> None:
    await api.world.service()

    response = api.client.get(api.url("/refund"), headers=api.owner)

    assert response.status_code == 200
    assert response.json() == {
        "eligible": True,
        "amount": 200_000,
        "reasonCode": None,
        "reasonFa": None,
        "windowHours": 24,
        # Bought an hour before the fixture's clock, with a 24-hour window.
        "deadlineAt": "2026-11-27T11:00:00Z",
        "policyFa": T.REFUND_POLICY.format(hours="۲۴"),
    }


async def test_a_used_service_is_not_offered(api: Api) -> None:
    sub = await api.world.service()
    sub.record_usage(used_mib=1, at=datetime(2026, 11, 26, 11, 30, tzinfo=UTC))

    body = api.client.get(api.url("/refund"), headers=api.owner).json()

    assert body["eligible"] is False
    assert body["amount"] is None
    assert body["reasonCode"] == "refund_service_used"
    assert body["reasonFa"] == "این سرویس استفاده شده و وجهش برنمی‌گرده."


async def test_a_shop_without_refunds_says_so(switched_off: Api) -> None:
    await switched_off.world.service()

    body = switched_off.client.get(switched_off.url("/refund"), headers=switched_off.owner).json()

    assert body["eligible"] is False
    assert body["reasonCode"] == "refund_disabled"
    assert body["windowHours"] == 0


async def test_asking_about_someone_elses_service_is_a_404(api: Api) -> None:
    await api.world.service()

    response = api.client.get(api.url("/refund"), headers=api.friend)

    _problem(response, 404, "subscription_not_found")


async def test_a_refund_credits_the_wallet_at_once(api: Api) -> None:
    sub = await api.world.service()

    response = api.client.post(api.url("/refund"), headers=api.owner)

    assert response.status_code == 200
    assert response.json() == {
        "subscriptionId": str(api.world.sub_id),
        "amount": 200_000,
        "messageFa": T.REFUND_DONE.format(amount=toman(200_000)),
    }
    assert sub.state.value == "revoked"
    assert api.world.sync.reports[-1].endswith("از طریق: اپ")


async def test_a_second_refund_is_refused_with_the_bots_reason(api: Api) -> None:
    await api.world.service()
    api.client.post(api.url("/refund"), headers=api.owner)

    response = api.client.post(api.url("/refund"), headers=api.owner)

    _problem(response, 409, "refund_service_not_active", "فقط سرویس فعال قابل برگشت وجهه.")


async def test_refunding_someone_elses_service_is_a_404(api: Api) -> None:
    sub = await api.world.service()

    response = api.client.post(api.url("/refund"), headers=api.friend)

    _problem(response, 404, "subscription_not_found")
    assert sub.state.value == "active"


async def test_refunding_when_the_shop_has_no_refunds(switched_off: Api) -> None:
    await switched_off.world.service()

    response = switched_off.client.post(switched_off.url("/refund"), headers=switched_off.owner)

    _problem(response, 409, "refund_disabled", "برگشت وجه در این فروشگاه فعال نیست.")


# -- every new route needs a signed-in customer --------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/devices"),
        ("post", f"/devices/{uuid.uuid4()}/revoke"),
        ("post", f"/subscriptions/{uuid.uuid4()}/name"),
        ("post", f"/subscriptions/{uuid.uuid4()}/transfer"),
        ("get", f"/subscriptions/{uuid.uuid4()}/refund"),
        ("post", f"/subscriptions/{uuid.uuid4()}/refund"),
    ],
)
def test_the_new_routes_refuse_an_anonymous_caller(app: FastAPI, method: str, path: str) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert getattr(client, method)(f"{MINIAPP}{path}").status_code == 401
