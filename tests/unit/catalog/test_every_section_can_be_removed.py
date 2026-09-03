"""Every section of the panel can remove a row, and each button reaches an API.

The operator could not delete anything: not a category, not a product, not a
package, not a server. Coupons were the only exception. Meanwhile the API had a
node DELETE that no client method existed for, and archive routes for the
catalogue that no screen ever called - correct code, reachable from nothing,
which is the failure mode this project keeps producing.

This is a contract between the two sides. Adding a removable thing without a
button, or a button without a route, fails here rather than being discovered by
somebody trying to tidy up their catalogue.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

CLIENT = pathlib.Path("admin/src/lib/api.ts")
ROUTERS = pathlib.Path("src/geekvpn/presentation/api/routers")

#: Screen, the client method it must call, and the route that must exist.
REMOVABLE = [
    ("admin/src/app/products/page.tsx", "archiveCategory", "admin_catalog.py", "/categories/{category_id}"),
    ("admin/src/app/products/page.tsx", "archiveProduct", "admin_catalog.py", "/products/{product_id}"),
    ("admin/src/app/products/page.tsx", "archivePlan", "admin_catalog.py", "/plans/{plan_id}"),
    ("admin/src/app/servers/page.tsx", "deleteNode", "admin_panels.py", "/{node_id}"),
    ("admin/src/app/coupons/page.tsx", "archiveCoupon", "admin_catalog.py", "/coupons/{coupon_id}"),
    ("admin/src/app/campaigns/page.tsx", "archiveCampaign", "admin_catalog.py", "/campaigns/{campaign_id}"),
]


@pytest.mark.parametrize(("screen", "method", "router", "route"), REMOVABLE)
def test_the_screen_offers_a_way_to_remove_a_row(screen, method, router, route):
    assert method in pathlib.Path(screen).read_text(encoding="utf-8"), (
        f"{screen} has no way to remove anything"
    )


@pytest.mark.parametrize(("screen", "method", "router", "route"), REMOVABLE)
def test_the_client_has_the_method_the_screen_calls(screen, method, router, route):
    assert f"{method}:" in CLIENT.read_text(encoding="utf-8")


@pytest.mark.parametrize(("screen", "method", "router", "route"), REMOVABLE)
def test_the_route_the_client_calls_exists(screen, method, router, route):
    source = (ROUTERS / router).read_text(encoding="utf-8")

    assert f'@router.delete(\n    "{route}"' in source, f"{route} has no DELETE in {router}"


def test_removing_from_the_catalogue_never_hard_deletes():
    """A plan is what an invoice names, and a receipt has to still render years
    from now. Every catalogue removal archives; only a server is really gone."""
    source = (ROUTERS / "admin_catalog.py").read_text(encoding="utf-8")

    for handler in ("archive_category", "archive_product", "archive_plan"):
        assert f"async def {handler}(" in source
    assert "delete_category" not in source
    assert "delete_plan" not in source


def test_a_server_still_carrying_customers_is_not_removed():
    """`subscriptions.node_id` is ON DELETE SET NULL, so this would orphan them
    silently: no usage read again, no renewal through us, and the accounts left
    behind on a panel nobody watches. Nothing about that raises on its own."""
    source = (ROUTERS / "admin_panels.py").read_text(encoding="utf-8")

    assert "SubscriptionState.ACTIVE" in source
    assert "HTTP_409_CONFLICT" in source


@pytest.mark.parametrize("screen", sorted({row[0] for row in REMOVABLE}))
def test_removal_is_confirmed_first(screen):
    """Every one of these takes a row off the screen with no undo beside it."""
    source = pathlib.Path(screen).read_text(encoding="utf-8")

    assert "window.confirm" in source, f"{screen} removes without asking"
