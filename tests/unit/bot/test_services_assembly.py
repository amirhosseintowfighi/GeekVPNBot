"""`BotServices` must actually be assembled and reach the handlers.

For the whole life of this codebase the bundle was never constructed anywhere,
so every handler that declared `services: BotServices` was handed `None` and the
bot crashed on first contact. These tests pin the two halves of the fix: the
bundle can be built from a request scope, and every slot in it is filled with
something that satisfies its port.
"""

from __future__ import annotations

import inspect
from dataclasses import fields

from geekvpn.application.bot import ports
from geekvpn.application.bot.services import BotServices
from geekvpn.infrastructure.bot.services import build_bot_services
from geekvpn.presentation.bot.identity import IdentityMiddleware

#: The port each slot of the bundle must satisfy.
_EXPECTED = {
    "subscriptions": ports.SubscriptionReader,
    "wallet": ports.WalletReader,
    "referrals": ports.ReferralReader,
    "profiles": ports.ProfileReader,
    "servers": ports.ServerStatusReader,
    "tickets": ports.TicketReader,
    "preferences": ports.PreferencesStore,
    "checkout": ports.CheckoutService,
}


class FakeClock:
    def now(self):
        from datetime import UTC, datetime

        return datetime(2026, 8, 7, tzinfo=UTC)


class FakeContainer:
    clock = FakeClock()
    sync_sessions = None


class FakeScope:
    """Only the attributes the assembly reads; none of them are called here."""

    container = FakeContainer()
    session = object()
    # `None` is the platform's own bot, which is what this assembly is for.
    # The attribute has to exist: the bundle reads it to decide which shop's
    # card the synchronous half will offer.
    reseller = None
    users = object()
    subscriptions = object()
    orders = object()
    nodes = object()
    quoting = object()
    order_service = object()
    catalog_plans = object()
    catalog_coupons = object()
    provisioning = object()


def test_every_slot_in_the_bundle_is_filled_by_something_satisfying_its_port() -> None:
    services = build_bot_services(FakeScope())  # type: ignore[arg-type]

    for name, port in _EXPECTED.items():
        assert isinstance(getattr(services, name), port), name


def test_the_test_covers_every_slot_the_bundle_declares() -> None:
    """Guards the test above: a new port must not slip in unchecked."""
    assert {f.name for f in fields(BotServices)} == set(_EXPECTED)


def test_the_identity_middleware_is_what_builds_the_bundle() -> None:
    """The bundle needs a session, so it cannot be built once per process.

    `create_dispatcher` used to take a `services` argument that nothing ever
    passed and that could not have worked; the seam is the per-update
    middleware instead.
    """
    source = inspect.getsource(IdentityMiddleware)
    assert 'data["services"]' in source
    assert "build_bot_services" in source


def test_the_dispatcher_no_longer_pretends_to_accept_a_services_bundle() -> None:
    from geekvpn.presentation.bot.factory import create_dispatcher

    assert "services" not in inspect.signature(create_dispatcher).parameters


def test_a_receipt_fetcher_can_be_threaded_all_the_way_to_checkout() -> None:
    """Without it the checkout adapter refuses receipts rather than digesting
    the file id, so the wiring has to survive the whole path."""

    async def fetch(file_id: str) -> bytes:  # pragma: no cover - identity only
        return b""

    services = build_bot_services(FakeScope(), fetch_receipt=fetch)  # type: ignore[arg-type]

    assert services.checkout._fetch_receipt is fetch  # type: ignore[attr-defined]
