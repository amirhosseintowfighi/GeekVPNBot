"""Every service in the sync scope must be constructible.

`engine` needed `events`, `events` needed the notification handlers, and those
handlers needed `engine`. Reading any one of them entered the cycle and died
with `RecursionError` - a 500 on approving a payment, refunding one, crediting
a wallet and sending a broadcast, which is most of what the panel exists to do.

Nothing caught it because nothing had ever constructed the sync scope's
notification stack outside the worker: the services had tests, the wiring had
none.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.di.sync_scope import SyncScope

pytestmark = pytest.mark.integration

#: Every service an admin request can reach through the sync scope.
SERVICES = (
    "engine",
    "events",
    "wallet_notifications",
    "purchase_notifications",
    "broadcast_service",
    "inbox",
    "review",
    "wallet",
    "support",
    "support_templates",
    "support_search",
    "support_notifier",
    "order_bridge",
    "reminders",
)

#: Left out on purpose: `refunds`, `checkout` and `verification` read the
#: gateway registry while being built, which needs a live session. They cannot
#: enter the cycle - none of them touches the notification engine - so covering
#: them here would buy a database fixture and nothing else.


@pytest.fixture
def scope(container) -> SyncScope:
    return SyncScope(container=container, session=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", SERVICES)
def test_the_service_can_be_built(scope: SyncScope, name: str) -> None:
    """Constructing must not recurse, and must not need a live session."""
    assert getattr(scope, name) is not None


def test_the_engine_and_its_publisher_are_the_same_dispatch_table(scope: SyncScope) -> None:
    """The deferral must not hand the engine a second, private publisher.

    An engine publishing into a table nobody else subscribes to is the failure
    the cycle was originally written to avoid, and it would look like working
    code: events go somewhere, and no handler ever runs.
    """
    engine_publisher = scope.engine._events

    # Publishing through the engine's handle must reach the scope's one table,
    # not a private second one.
    assert engine_publisher._resolve() is scope.events
