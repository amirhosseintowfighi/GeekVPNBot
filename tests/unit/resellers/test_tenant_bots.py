"""One process, many bots: the path and the secret that keep them apart.

A reseller runs their own bot under their own @username, and their customers
never see this platform. Serving several from one process is only possible
because everything here is webhook-driven - polling needs a connection per
token, a webhook needs a route per token, and a route is free.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.resellers.tenant_bots import tenant_path, tenant_secret

pytestmark = pytest.mark.unit

SECRET = "platform-webhook-secret"
ONE = uuid.UUID("11111111-1111-4111-8111-111111111111")
TWO = uuid.UUID("22222222-2222-4222-8222-222222222222")


def test_each_reseller_gets_their_own_path():
    assert tenant_path("/telegram/webhook", ONE) != tenant_path("/telegram/webhook", TWO)


def test_the_path_sits_under_the_platforms_own():
    """So an edge that forwards the bot's path forwards every tenant with it.

    Beside it instead, a reseller's bot silently receives nothing because nginx
    was never told about a second location - and nothing about that failure
    looks like a configuration problem from either end.
    """
    assert tenant_path("/telegram/webhook", ONE).startswith("/telegram/webhook/")


def test_a_trailing_slash_does_not_double_up():
    assert "//" not in tenant_path("/telegram/webhook/", ONE)


def test_each_reseller_gets_their_own_secret():
    """Not a shared one. A single value across every tenant means a leak from
    one reseller's edge authenticates traffic claiming to be any of them."""
    assert tenant_secret(SECRET, ONE) != tenant_secret(SECRET, TWO)


def test_the_secret_is_stable():
    """Derived, not stored - so nothing has to be kept in sync, and a restart
    does not invalidate a webhook Telegram already holds."""
    assert tenant_secret(SECRET, ONE) == tenant_secret(SECRET, ONE)


def test_a_new_platform_secret_changes_every_tenant():
    """Rotating the platform secret is a deliberate mass invalidation. It has
    to be, or a compromised secret could not be retired."""
    assert tenant_secret(SECRET, ONE) != tenant_secret("something-else", ONE)


def test_the_secret_is_shaped_the_way_telegram_accepts():
    """1-256 characters of A-Za-z0-9_- only. A value Telegram rejects means
    `setWebhook` fails and the reseller's bot never receives anything."""
    secret = tenant_secret(SECRET, ONE)

    assert 1 <= len(secret) <= 256
    assert all(c.isalnum() or c in "_-" for c in secret)


def test_the_platform_secret_is_not_recoverable_from_a_tenants():
    """A reseller's edge holds their own secret. It must not be the platform's
    secret in a hat."""
    assert SECRET not in tenant_secret(SECRET, ONE)


def test_a_tenants_updates_carry_the_shop_they_arrived_at():
    """The trap this whole file exists to avoid.

    A reseller's customer talking to the reseller's bot must not be answered
    with our storefront: our prices, our wallet and our brand, under a name
    they believe belongs to somebody else. That is worse than silence, and
    nobody would notice it was happening.

    The dispatcher is deliberately the same one - aiogram attaches a `Router`
    to exactly one dispatcher, so a second dispatcher over the same modules is
    not possible, and two sets of routers would be two things to keep in step.
    What makes the difference is `reseller_id` travelling with the update:
    every handler downstream is shared, so nothing can know which shop this is
    unless the route says so.

    Read from the source, because the mistake is one missing keyword argument
    in a handler no test can reach without a live Telegram token.
    """
    import ast
    import pathlib as _pathlib

    source = _pathlib.Path("src/geekvpn/presentation/bot/app.py").read_text(encoding="utf-8")
    handler = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "tenant_webhook"
    )
    feeds = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "feed_update"
    ]

    assert feeds, "the tenant route feeds nothing"
    for call in feeds:
        passed = {keyword.arg for keyword in call.keywords}
        assert "reseller_id" in passed, "an unscoped update is our shop under their name"
        # And no duck: a reseller's brand is not ours to decorate.
        assert "stickers" in passed


def test_the_platform_bot_does_not_claim_a_shop():
    """The other direction. Our own webhook must not pass a reseller id, or
    every customer of ours would be authenticated into somebody else's shop."""
    import ast
    import pathlib as _pathlib

    source = _pathlib.Path("src/geekvpn/presentation/bot/app.py").read_text(encoding="utf-8")
    handler = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "telegram_webhook"
    )
    for call in ast.walk(handler):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "feed_update"
        ):
            assert "reseller_id" not in {keyword.arg for keyword in call.keywords}
