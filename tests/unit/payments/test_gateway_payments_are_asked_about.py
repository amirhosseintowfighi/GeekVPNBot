"""A payment waiting at a gateway is asked about - by the worker, and when
the provider knocks - and always in the shop the payment belongs to.

`VerificationService.sweep` existed with tests and nothing called it, so an
AtlasPay payment approved in AtlasPay's bot was never noticed by this one.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks

from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.domain.payments.gateway import VerificationResult
from geekvpn.entrypoints.worker import Worker
from geekvpn.infrastructure.payments import gateway_verification as gv
from geekvpn.presentation.api.routers import gateway_callback

pytestmark = pytest.mark.unit

SHOP = uuid.uuid4()


class _Session:
    def __init__(self, rows: dict[str, Any]) -> None:
        self.rows = rows
        self.commits = 0
        self.rollbacks = 0

    def get(self, _model: Any, key: str) -> Any:
        return self.rows.get(key)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _container(session: _Session) -> Any:
    @contextmanager
    def sessions() -> Any:
        yield session

    return SimpleNamespace(sync_sessions=sessions)


def test_the_worker_asks_about_gateway_payments() -> None:
    worker = Worker(SimpleNamespace())  # type: ignore[arg-type]

    jobs = {name: interval for name, interval, _ in worker._periodic}

    # AtlasPay's own guidance is every 15 to 30 seconds.
    assert jobs["gateway_verify"] <= 30


def test_a_payment_is_verified_in_its_own_shop(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session({"p1": SimpleNamespace(reseller_id=SHOP)})
    shops: list[Any] = []
    confirmed = VerificationResult(outcome=VerificationOutcome.CONFIRMED)

    def build(container: Any, session: Any, *, reseller_id: Any = None) -> Any:
        shops.append(reseller_id)
        return SimpleNamespace(verification=SimpleNamespace(verify=lambda _id: confirmed))

    monkeypatch.setattr(gv, "build_sync_scope", build)

    result = gv.verify_payment(_container(session), "p1")

    assert result is confirmed
    # The reseller's registry, so the reseller's merchant key is the one asked.
    assert shops == [SHOP]
    assert session.commits == 1


def test_one_payment_failing_does_not_stop_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def verify(_container: Any, payment_id: str) -> VerificationResult:
        asked.append(payment_id)
        if payment_id == "broken":
            raise RuntimeError("gateway down")
        return VerificationResult(outcome=VerificationOutcome.CONFIRMED)

    monkeypatch.setattr(gv, "waiting_at_a_gateway", lambda _c: ["broken", "fine"])
    monkeypatch.setattr(gv, "verify_payment", verify)

    counts = gv.sweep_gateways(SimpleNamespace())  # type: ignore[arg-type]

    assert asked == ["broken", "fine"]
    assert counts == {"error": 1, str(VerificationOutcome.CONFIRMED): 1}


@pytest.mark.asyncio
async def test_a_providers_knock_is_answered_at_once_and_verified_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AtlasPay's webhook: it waits five seconds and never retries, so the
    answer comes first and the asking happens after."""
    asked: list[str] = []
    monkeypatch.setattr(
        gateway_callback, "verify_payment", lambda _container, payment_id: asked.append(payment_id)
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=object())))
    background = BackgroundTasks()

    response = await gateway_callback.gateway_notification("p1", request, background)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert asked == []
    await background()
    assert asked == ["p1"]
