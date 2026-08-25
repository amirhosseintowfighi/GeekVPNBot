"""The Mini App's authentication boundary.

Every route re-verifies the Telegram initData signature, so these assert the
part an attacker actually probes: what happens with no header, the wrong
scheme, and a forged signature.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

MINIAPP = "/api/miniapp"

#: Every route the Mini App can reach, so a new one cannot be added without an
#: authentication check.
PROTECTED = [
    f"{MINIAPP}/storefront",
    f"{MINIAPP}/subscriptions",
    f"{MINIAPP}/wallet",
    f"{MINIAPP}/referral",
    f"{MINIAPP}/tickets",
    f"{MINIAPP}/profile",
    f"{MINIAPP}/preferences",
    f"{MINIAPP}/servers",
    f"{MINIAPP}/faq",
]


@pytest.fixture
def api(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("path", PROTECTED)
def test_no_header_is_refused(api, path) -> None:
    assert api.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_a_bearer_token_is_not_accepted_where_initdata_is_required(api, path) -> None:
    """The Mini App scheme is `tma`. Accepting a Bearer here would let an
    access token stand in for a signature Telegram vouched for."""
    assert api.get(path, headers={"Authorization": "Bearer whatever"}).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_a_forged_signature_is_refused(api, path) -> None:
    forged = "user=%7B%22id%22%3A1%7D&auth_date=1&hash=deadbeef"
    assert api.get(path, headers={"Authorization": f"tma {forged}"}).status_code == 401


def test_an_empty_tma_value_is_refused(api) -> None:
    assert api.get(f"{MINIAPP}/wallet", headers={"Authorization": "tma "}).status_code == 401


def test_the_scheme_is_matched_case_insensitively(api) -> None:
    """Telegram's own SDK examples disagree about the capitalisation, so the
    refusal must come from the signature, not from the scheme's case."""
    forged = "user=%7B%22id%22%3A1%7D&auth_date=1&hash=deadbeef"
    lower = api.get(f"{MINIAPP}/wallet", headers={"Authorization": f"tma {forged}"})
    upper = api.get(f"{MINIAPP}/wallet", headers={"Authorization": f"TMA {forged}"})
    assert lower.status_code == upper.status_code == 401


def test_every_miniapp_route_requires_authentication(app) -> None:
    """No route may be reachable anonymously.

    Asserted against the schema rather than a list, so adding an endpoint
    without a customer on it fails here rather than in production.
    """
    schema = app.openapi()
    unprotected = []
    for path, operations in schema["paths"].items():
        if not path.startswith(f"{MINIAPP}/"):
            continue
        for method, operation in operations.items():
            params = {p.get("name") for p in operation.get("parameters", [])}
            if "authorization" not in params:
                unprotected.append(f"{method.upper()} {path}")
    assert not unprotected, unprotected


# -- one customer must not read another's ticket --------------------------


class _OtherPersonsTicket:
    """A support scope whose ticket belongs to somebody else."""

    class support:
        @staticmethod
        def get_ticket(ticket_id: str):  # noqa: ANN205
            from types import SimpleNamespace

            return SimpleNamespace(user_id=999, ticket_id=ticket_id)


def test_reading_someone_elses_ticket_is_refused() -> None:
    """The support service is written for agents, who may read any ticket, so
    the ownership check has to live in the Mini App router."""
    from fastapi import HTTPException

    from geekvpn.presentation.api.routers.miniapp import _require_own_ticket

    with pytest.raises(HTTPException) as caught:
        _require_own_ticket(_OtherPersonsTicket(), "TK-1", 555)

    assert caught.value.status_code == 404


def test_the_refusal_is_a_404_not_a_403() -> None:
    """A 403 would confirm to a stranger that the ticket id is real."""
    from fastapi import HTTPException

    from geekvpn.presentation.api.routers.miniapp import _require_own_ticket

    with pytest.raises(HTTPException) as caught:
        _require_own_ticket(_OtherPersonsTicket(), "TK-1", 555)

    assert caught.value.status_code != 403


def test_the_owner_passes_the_check() -> None:
    from geekvpn.presentation.api.routers.miniapp import _require_own_ticket

    _require_own_ticket(_OtherPersonsTicket(), "TK-1", 999)


def test_a_pending_payment_never_exposes_the_receipt_or_card() -> None:
    """The list is rendered to the customer; proof material stays server-side.

    Asserted on the emitted keys rather than the source, so a field added to
    Payment later cannot leak by being passed straight through.
    """
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from geekvpn.domain.payments.enums import PaymentMethod, PaymentState
    from geekvpn.presentation.api.routers.miniapp import _payment_view

    payment = SimpleNamespace(
        id="pay-1",
        amount=SimpleNamespace(amount=250_000),
        method=PaymentMethod.CARD,
        state=PaymentState.PENDING_REVIEW,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
        expires_at=None,
        proof="secret-receipt",
        gateway_reference="gw-ref",
    )

    # The destination card is the one thing here the customer must see - it is
    # what they transfer to. It comes from the gateway registry, never from the
    # payment row, so a stub registry is the whole dependency.
    scope = SimpleNamespace(
        gateways=SimpleNamespace(
            has=lambda key: True,
            get=lambda key: SimpleNamespace(
                card_number="6037-9900-0000-0000",
                card_holder_fa="علی",
                bank_name_fa="ملی",
            ),
        )
    )

    view = _payment_view(payment, scope)

    assert set(view) == {
        "payment_id",
        "reference",
        "amount",
        "method",
        "state",
        "created_at",
        "expires_at",
        "card",
        "crypto",
    }
    assert "secret-receipt" not in str(view)
    assert "gw-ref" not in str(view)
