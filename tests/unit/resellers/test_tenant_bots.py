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


def test_a_tenants_updates_never_reach_the_platform_dispatcher():
    """The trap this whole file exists to avoid.

    A reseller's customer talking to the reseller's bot must not be answered
    by our storefront: our prices, our wallet and our brand, under a name they
    believe belongs to somebody else. That is worse than silence, and nobody
    would notice it was happening.

    Read from the source, because the mistake is one identifier: `dispatcher`
    instead of `reseller_dispatcher`, in a handler no test can reach without a
    live Telegram token.
    """
    import ast
    import pathlib

    source = pathlib.Path("src/geekvpn/presentation/bot/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "tenant_webhook"
    )

    fed = {
        ast.unparse(node.func.value)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "feed_update"
    }

    assert fed
    assert not any("app.state.dispatcher" in target for target in fed), fed
