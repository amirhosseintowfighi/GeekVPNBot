"""The admin panel and the backend must agree on the URLs.

This whole class of bug - a front-end built against endpoints that were never
registered - is why the admin panel shipped unusable. A reviewer cannot catch it
by reading either side alone, so it is pinned here instead.

The test extracts the paths `admin/src` actually calls, normalises them, and
compares them with the routes `create_app()` registers. `KNOWN_GAPS` is the
explicit list of calls with no backend yet: it must only ever shrink, and the
test fails both when a *new* mismatch appears and when a listed gap is quietly
fixed without being removed here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from geekvpn.presentation.api.app import API_V1_PREFIX, create_app

pytestmark = pytest.mark.integration

ADMIN_SRC = Path(__file__).resolve().parents[2] / "admin" / "src"

#: Endpoints the admin panel calls that the backend does not serve yet. Each one
#: is a real missing feature, not a naming difference - the naming differences
#: were fixed. Remove an entry the moment its route is registered.
KNOWN_GAPS: frozenset[str] = frozenset(
    {
        # Broadcast composition and dispatch. BroadcastService exists but has no
        # SQL AudienceResolver, so no router can be built on it yet.
        f"{API_V1_PREFIX}/admin/broadcasts",
        f"{API_V1_PREFIX}/admin/broadcasts/{{id}}/cancel",
        f"{API_V1_PREFIX}/admin/broadcasts/{{id}}/send",
        f"{API_V1_PREFIX}/admin/broadcasts/estimate",
        # Bulk plan generation across a duration ladder.
        f"{API_V1_PREFIX}/admin/duration-ladder",
        f"{API_V1_PREFIX}/admin/catalog/plans/generate-ladder",
        # Nested creation; plans are currently created through /catalog/plans.
        f"{API_V1_PREFIX}/admin/catalog/products/{{id}}/plans",
        # Re-reading account counts from a panel on demand.
        f"{API_V1_PREFIX}/admin/panels/{{id}}/sync",
        # Issuing a customer a fresh subscription link.
        f"{API_V1_PREFIX}/admin/subscriptions/{{id}}/rotate",
        # Admin sign-out. Session revocation lives under /api/v1/auth/logout,
        # which is not under the /admin prefix this client builds from.
        f"{API_V1_PREFIX}/admin/auth/sign-out",
        # Wallet routes are per-customer server-side (/wallets/{user_id}/...)
        # but the client calls them without an id.
        f"{API_V1_PREFIX}/admin/wallet/adjust",
        f"{API_V1_PREFIX}/admin/wallet/transactions",
        # Not a rename: the backend models approve/reject/refund as actions on a
        # *payment* (/admin/payments/{payment_id}/...), while the client holds an
        # order id. Closing this needs the order detail response to carry its
        # payment id, so it is a contract change rather than a path edit.
        f"{API_V1_PREFIX}/admin/orders/{{id}}/approve",
        f"{API_V1_PREFIX}/admin/orders/{{id}}/reject",
        f"{API_V1_PREFIX}/admin/orders/{{id}}/refund",
    }
)

_TEMPLATE = re.compile(r"\$\{[^}]*\}")


def called_paths() -> set[str]:
    """Every `${ROOT}/...` template literal the admin client builds."""
    found: set[str] = set()
    for file in ADMIN_SRC.rglob("*.ts"):
        for raw in re.findall(r"\$\{ROOT\}/[^`'\"\s,)]*", file.read_text(encoding="utf-8")):
            # A trailing `${qs(...)}` is a query string, not a path segment.
            path = raw.split("${qs")[0]
            # Expand ${ROOT} before collapsing the rest, or the prefix itself
            # becomes an {id} segment.
            path = path.replace("${ROOT}", f"{API_V1_PREFIX}/admin")
            found.add(_TEMPLATE.sub("{id}", path).rstrip("/"))
    return found


def registered_paths() -> set[str]:
    """Registered routes with their parameter names normalised away."""
    return {
        _TEMPLATE.sub("{id}", re.sub(r"\{[^}]*\}", "{id}", path))
        for path in create_app().openapi()["paths"]
    }


def test_the_admin_client_is_actually_reading_from_a_real_directory() -> None:
    """Guards the test itself: a bad path would make everything below vacuous."""
    assert ADMIN_SRC.is_dir()
    assert called_paths()


def test_every_endpoint_the_admin_panel_calls_is_registered() -> None:
    missing = called_paths() - registered_paths() - KNOWN_GAPS
    assert not missing, (
        "The admin panel calls endpoints the backend does not serve:\n  "
        + "\n  ".join(sorted(missing))
        + "\nEither register the route or add it to KNOWN_GAPS with a reason."
    )


def test_no_known_gap_has_been_quietly_closed() -> None:
    """Keeps the gap list honest.

    A gap that got implemented but stayed listed would hide the next real
    regression behind a stale exemption.
    """
    closed = KNOWN_GAPS & registered_paths()
    assert not closed, (
        "These are now registered and must be removed from KNOWN_GAPS:\n  "
        + "\n  ".join(sorted(closed))
    )
