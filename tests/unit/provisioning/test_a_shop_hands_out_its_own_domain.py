"""A reseller's customers get a link on the reseller's domain.

The panel is ours and the token is the panel's, but the customer is theirs, and
a link on our domain in their bot undoes the point of them having one. So the
host is overridable per shop - and per node, because a subscription token only
means anything to the panel that minted it: one shop-wide host would send every
customer bought from a second panel to a server that has never heard of them.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.claim_service import ClaimOutcome, ClaimService
from geekvpn.application.provisioning.links import link_host, public_link
from geekvpn.domain.panels.enums import AccountState
from geekvpn.domain.panels.values import (
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
    TrafficQuota,
)
from tests.unit.provisioning.test_claiming_an_existing_account import (
    FakeNode,
    FakeSubscriptions,
    FixedClock,
)
from tests.unit.provisioning.test_which_panel_the_link_came_from import (
    Nodes,
    Panels,
    RecordingAdapter,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)
GIB = 1024**3
TOKEN = "djMsMSwxNzg4NDQxMjYw"

API = "https://panel.doping.games:8443"
OURS = "https://panel2.hostcheap.top"
THEIRS = "https://dgfytygh.sdfgh.com"


# -- the rule itself -------------------------------------------------------


def test_the_shops_own_domain_wins_over_the_nodes():
    assert link_host("n1", OURS, {"n1": THEIRS}) == THEIRS


def test_the_node_is_the_fallback():
    """A shop that has not been given a domain still gets a working link."""
    assert link_host("n1", OURS, {}) == OURS
    assert link_host("n1", OURS, None) == OURS


def test_a_domain_for_another_node_does_not_leak_across():
    """The failure this shape exists to prevent: a shop with one domain
    recorded, selling from a second panel, must not have that panel's links
    rewritten onto a host that never minted the token."""
    assert link_host("n2", OURS, {"n1": THEIRS}) == OURS


def test_no_host_anywhere_leaves_the_panels_answer_alone():
    assert link_host("n1", None, {}) is None
    assert public_link(f"{API}/sub/{TOKEN}", link_host("n1", None, {})) == f"{API}/sub/{TOKEN}"


# -- through the claim -----------------------------------------------------


def _account() -> PanelAccount:
    return PanelAccount(
        ref=PanelAccountRef(panel_id=__import__("uuid").uuid4(), username="amir"),
        state=AccountState.ACTIVE,
        usage=AccountUsage(used_bytes=GIB, measured_at=NOW, quota=TrafficQuota(50 * GIB)),
        expires_at=NOW + timedelta(days=10),
        subscription_url=f"{API}/sub/{TOKEN}",
    )


def _claim(shop_hosts):
    order: list[str] = []
    node = FakeNode("ours", base_url=API, subscription_base_url=OURS)
    subs = FakeSubscriptions()
    service = ClaimService(
        subscriptions=subs,
        nodes=Nodes([node]),
        panels=Panels({"ours": RecordingAdapter(order, "ours", _account())}),
        clock=FixedClock(),
        shop_hosts=shop_hosts,
    )
    result = asyncio.run(service.claim(url=f"{API}/sub/{TOKEN}", user_id=1, reseller_id="r1"))
    assert result.outcome is ClaimOutcome.CLAIMED
    return subs.added[0]


def test_a_resellers_customer_is_handed_the_resellers_domain():
    assert _claim({"ours": THEIRS}).subscription_url == f"{THEIRS}/sub/{TOKEN}"


def test_our_own_customer_is_handed_ours():
    """No shop, so no override - the node's host stands."""
    assert _claim(None).subscription_url == f"{OURS}/sub/{TOKEN}"
