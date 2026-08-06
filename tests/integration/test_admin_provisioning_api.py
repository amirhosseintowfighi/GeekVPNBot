"""The admin routes that make the platform sellable.

Until these existed an operator could not add a node, which meant provisioning
had nothing to select and every paid order failed. These tests assert the two
properties that matter most about them: the permission guard is real, and the
panel password never appears in a response.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.api.app import API_V1_PREFIX

pytestmark = pytest.mark.integration

ADMIN = f"{API_V1_PREFIX}/admin"


def token(container, *permissions: Permission) -> str:
    return container.access_tokens.issue(
        subject_type=SubjectType.ADMIN,
        subject_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role=None,
        permissions=list(permissions),
    ).value


def auth(container, *permissions: Permission) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(container, *permissions)}"}


@pytest.fixture
def api(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# -- registration ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        f"{ADMIN}/panels",
        f"{ADMIN}/orders",
        f"{ADMIN}/subscriptions",
        f"{ADMIN}/customers",
    ],
)
def test_every_provisioning_admin_collection_is_registered(app, path) -> None:
    """A router that exists but is not included in `app.py` is dead code, which
    is the exact failure this whole area is being fixed for."""
    assert path in app.openapi()["paths"]


# -- authorization ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        f"{ADMIN}/panels",
        f"{ADMIN}/orders",
        f"{ADMIN}/subscriptions",
        f"{ADMIN}/customers",
    ],
)
def test_listing_requires_a_token(api, path) -> None:
    assert api.get(path).status_code == 401


def test_adding_a_node_requires_panels_write(api, container) -> None:
    response = api.post(
        f"{ADMIN}/panels",
        headers=auth(container, Permission.PANELS_READ),
        json={
            "id": "fra-1",
            "name_fa": "فرانکفورت",
            "panel_kind": "marzban",
            "base_url": "https://panel.example.ir",
            "username": "admin",
            "password": "hunter2hunter2",
        },
    )
    assert response.status_code == 403


def test_reading_nodes_requires_only_panels_read(api, container) -> None:
    response = api.get(f"{ADMIN}/panels", headers=auth(container, Permission.PANELS_READ))
    assert response.status_code == 200
    assert response.json() == []


def test_suspending_a_customer_requires_users_suspend(api, container) -> None:
    response = api.post(
        f"{ADMIN}/customers/{uuid.uuid4()}/suspend",
        headers=auth(container, Permission.USERS_READ),
        json={"reason": "پرداخت جعلی"},
    )
    assert response.status_code == 403


def test_retry_provision_requires_subscriptions_write(api, container) -> None:
    response = api.post(
        f"{ADMIN}/orders/ord-1/retry-provision",
        headers=auth(container, Permission.ORDERS_READ),
    )
    assert response.status_code == 403


# -- the password must never come back ------------------------------------


def test_the_node_schema_has_no_password_field() -> None:
    """Asserted against the schema, not one response body.

    A response that happens to omit the password today would start including it
    the moment someone adds the column to the model, so the guarantee has to be
    made about the contract itself.
    """
    from geekvpn.presentation.api.routers.admin_panels import NodeResponse

    fields = set(NodeResponse.model_fields)
    assert "password" not in fields
    assert "password_encrypted" not in fields
    assert "has_password" in fields


def test_a_missing_node_is_a_404_not_a_500(api, container) -> None:
    response = api.get(f"{ADMIN}/panels/nope", headers=auth(container, Permission.PANELS_READ))
    assert response.status_code == 404


def test_a_missing_customer_is_a_404(api, container) -> None:
    response = api.get(
        f"{ADMIN}/customers/{uuid.uuid4()}", headers=auth(container, Permission.USERS_READ)
    )
    assert response.status_code == 404


def test_an_unknown_order_cannot_be_retried(api, container) -> None:
    response = api.post(
        f"{ADMIN}/orders/nope/retry-provision",
        headers=auth(container, Permission.SUBSCRIPTIONS_WRITE),
    )
    assert response.status_code == 404
