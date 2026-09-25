"""The Android app's shop additions: free trial, receipt upload, the way back.

Persistence underneath is the permanently empty test container, so these pin
the wire: what is refused before any work is done, what the trial answers, and
what the bank's return page offers. The trial's rules themselves are covered by
`tests/unit/provisioning/test_free_trial.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.application.provisioning.free_trial import TrialDelivery, TrialOffer
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.user import User
from geekvpn.domain.provisioning.errors import FreeTrialAlreadyClaimed
from geekvpn.infrastructure.di.container import Container
from geekvpn.presentation.api.routers.gateway_callback import remember_app_payment
from geekvpn.presentation.api.routers.miniapp import MAX_RECEIPT_BYTES
from geekvpn.presentation.api.security import get_scope
from tests.fakes import FrozenClock, InMemoryUserRepository, RecordingAudit

pytestmark = pytest.mark.integration

TELEGRAM_ID = 555


@dataclass
class FakeTrial:
    claimed: set[int] = field(default_factory=set)

    async def offer(self, user_id: int) -> TrialOffer:
        return TrialOffer(available=user_id not in self.claimed)

    async def place(self, user_id: int) -> list[str]:
        if user_id in self.claimed:
            raise FreeTrialAlreadyClaimed("Already had it.", user_id=user_id)
        self.claimed.add(user_id)
        return ["ord-1", "ord-2"]

    async def deliver(self, orders: list[str]) -> TrialDelivery:
        return TrialDelivery(subscriptions=(), pending=len(orders))


class _Scope:
    """What the Mini App's authentication and the trial routes read."""

    def __init__(self, container: Container, users: InMemoryUserRepository) -> None:
        assert container.telegram_auth is not None
        self.authenticate_telegram = AuthenticateTelegramUser(
            users=users,
            verifier=container.telegram_auth,
            sessions=None,  # type: ignore[arg-type] - verification never issues tokens
            clock=FrozenClock(),
            audit=RecordingAudit(),
        )
        self.free_trial = FakeTrial()


@pytest.fixture
def world(app: FastAPI, container: Container) -> Iterator[tuple[TestClient, dict[str, str]]]:
    users = InMemoryUserRepository()
    user = User.register(user_id=uuid.uuid4(), telegram_id=TELEGRAM_ID, referral_code="R555")
    users.items[user.id] = user
    scope = _Scope(container, users)
    app.dependency_overrides[get_scope] = lambda: scope
    token = container.access_tokens.issue(
        subject_type=SubjectType.USER, subject_id=user.id, session_id=uuid.uuid4()
    ).value
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, {"Authorization": f"Bearer {token}"}
    app.dependency_overrides.clear()


# -- free trial ------------------------------------------------------------------


def test_the_trial_offer_says_what_it_is(world: tuple[TestClient, dict[str, str]]) -> None:
    client, auth = world

    response = client.get("/api/miniapp/trial", headers=auth)

    assert response.status_code == 200
    assert response.json() == {"available": True, "trafficMib": 50, "durationDays": 2}


def test_claiming_reports_what_is_still_on_the_way(
    world: tuple[TestClient, dict[str, str]],
) -> None:
    client, auth = world

    response = client.post("/api/miniapp/trial", headers=auth)

    assert response.status_code == 200
    assert response.json() == {"subscriptionIds": [], "pending": 2}
    assert client.get("/api/miniapp/trial", headers=auth).json()["available"] is False


def test_a_second_claim_is_a_409_with_persian_copy(
    world: tuple[TestClient, dict[str, str]],
) -> None:
    client, auth = world
    client.post("/api/miniapp/trial", headers=auth)

    response = client.post("/api/miniapp/trial", headers=auth)

    assert response.status_code == 409
    assert response.json()["title"] == "free_trial_already_claimed"
    assert response.json()["message_fa"]


def test_the_trial_needs_a_signed_in_customer(app: FastAPI) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/miniapp/trial").status_code == 401


# -- receipt photo ---------------------------------------------------------------


def _receipt_url() -> str:
    return f"/api/miniapp/payments/{uuid.uuid4()}/receipt-photo"


def test_a_receipt_must_be_an_image(world: tuple[TestClient, dict[str, str]]) -> None:
    client, auth = world

    response = client.post(
        _receipt_url(), content=b"%PDF-1.7", headers={**auth, "Content-Type": "application/pdf"}
    )

    assert response.status_code == 415


def test_an_oversized_receipt_is_refused(world: tuple[TestClient, dict[str, str]]) -> None:
    client, auth = world

    response = client.post(
        _receipt_url(),
        content=b"\xff" * (MAX_RECEIPT_BYTES + 1),
        headers={**auth, "Content-Type": "image/jpeg"},
    )

    assert response.status_code == 413


def test_an_empty_receipt_is_refused(world: tuple[TestClient, dict[str, str]]) -> None:
    client, auth = world

    response = client.post(
        _receipt_url(), content=b"", headers={**auth, "Content-Type": "image/png"}
    )

    assert response.status_code == 422


# -- the bank's return page ------------------------------------------------------


async def test_a_payment_the_app_started_is_handed_back_to_the_app(
    app: FastAPI, container: Container
) -> None:
    payment_id = uuid.uuid4()
    await remember_app_payment(container.cache, payment_id)

    with TestClient(app, raise_server_exceptions=False) as client:
        page = client.get(f"/pay/callback/{payment_id.hex}").text

    assert f"geekvpn://payment/result?payment={payment_id.hex}" in page
    assert "بازگشت به اپ" in page


def test_any_other_payment_keeps_pointing_at_the_bot(app: FastAPI) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        page = client.get(f"/pay/callback/{uuid.uuid4().hex}").text

    assert "geekvpn://" not in page
