"""Node selection is a pure function, so it is tested like one."""

from __future__ import annotations

import pytest

from geekvpn.application.provisioning.node_selector import eligible_nodes, select_node
from geekvpn.domain.provisioning.enums import NodeState
from geekvpn.domain.provisioning.errors import NoCapacityAvailable
from tests.unit.provisioning.fakes import node


def test_prefers_the_least_loaded_node() -> None:
    busy = node("busy", capacity=100, account_count=90)
    quiet = node("quiet", capacity=100, account_count=10)

    assert select_node([busy, quiet]).id == "quiet"


def test_a_full_node_is_not_a_candidate() -> None:
    full = node("full", capacity=10, account_count=10)
    room = node("room", capacity=10, account_count=9)

    assert [n.id for n in eligible_nodes([full, room])] == ["room"]


def test_zero_capacity_means_uncapped_not_full() -> None:
    uncapped = node("uncapped", capacity=0, account_count=5_000)

    assert select_node([uncapped]).id == "uncapped"


@pytest.mark.parametrize(
    "state",
    [NodeState.DEGRADED, NodeState.OFFLINE, NodeState.MAINTENANCE, NodeState.RETIRED],
)
def test_only_online_nodes_take_new_accounts(state: NodeState) -> None:
    """A degraded node still serves existing customers and must not get new ones."""
    with pytest.raises(NoCapacityAvailable):
        select_node([node("n", state=state)])


def test_an_operator_can_close_a_node_to_new_customers() -> None:
    with pytest.raises(NoCapacityAvailable):
        select_node([node("n", accepting_new=False)])


def test_country_is_a_promise_not_a_preference() -> None:
    """Selling a German plan and delivering a Dutch node is the wrong product."""
    dutch = node("nl", country_code="NL", account_count=0, capacity=100)

    with pytest.raises(NoCapacityAvailable):
        select_node([dutch], country_code="DE")


def test_country_match_wins_over_load_balance() -> None:
    german_busy = node("de", country_code="DE", capacity=100, account_count=95)
    dutch_empty = node("nl", country_code="NL", capacity=100, account_count=0)

    assert select_node([german_busy, dutch_empty], country_code="de").id == "de"


def test_selection_is_deterministic_on_a_tie() -> None:
    a = node("aaa", capacity=100, account_count=10, sort_order=1)
    b = node("bbb", capacity=100, account_count=10, sort_order=1)

    assert select_node([a, b]).id == select_node([b, a]).id == "aaa"


def test_sort_order_breaks_a_load_tie_before_the_id_does() -> None:
    preferred = node("zzz", capacity=100, account_count=10, sort_order=0)
    other = node("aaa", capacity=100, account_count=10, sort_order=5)

    assert select_node([preferred, other]).id == "zzz"
