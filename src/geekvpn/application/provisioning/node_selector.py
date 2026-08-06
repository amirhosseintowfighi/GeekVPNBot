"""Which server does this order land on.

A pure function over :class:`NodeRecord`. No I/O, no clock, no randomness, so
the answer to "why did order 1405-0042 land on Frankfurt" is reproducible from
the row values alone.

The ordering rules, in priority order:

1. The node must be usable at all: state accepts new accounts, the operator has
   not closed it, and it has room.
2. A requested country wins over a better-balanced node elsewhere. Somebody who
   bought a German plan and got a Dutch one has received the wrong product, and
   balancing is not a reason to ship the wrong product.
3. Then least loaded, so capacity drains evenly rather than filling one node
   until it falls over.
4. Then the operator's explicit ``sort_order``, then the id. The last tiebreak
   exists so selection is deterministic in tests and in incident review.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from geekvpn.application.provisioning.ports import NodeRecord
from geekvpn.domain.provisioning.errors import NoCapacityAvailable


def eligible_nodes(
    nodes: Iterable[NodeRecord], *, country_code: str | None = None
) -> tuple[NodeRecord, ...]:
    """Every node that could take this account, best first.

    :param nodes: candidates, in any order.
    :param country_code: ISO-3166 alpha-2 the customer bought. ``None`` means
        the plan is country-agnostic and any node is correct.
    :returns: a sorted tuple, possibly empty.
    """
    wanted = country_code.upper() if country_code else None
    usable = [
        node
        for node in nodes
        if node.state.accepts_new_accounts and node.accepting_new and node.has_room
    ]
    if wanted is not None:
        matching = [node for node in usable if (node.country_code or "").upper() == wanted]
        # An empty match is a real answer: the plan promised a country we cannot
        # currently deliver, and silently substituting another is worse than
        # failing loudly into the retry queue.
        usable = matching
    return tuple(sorted(usable, key=lambda node: (node.load_ratio, node.sort_order, node.id)))


def select_node(nodes: Sequence[NodeRecord], *, country_code: str | None = None) -> NodeRecord:
    """Pick the node a new account should be created on.

    :raises NoCapacityAvailable: when nothing is eligible. The caller is
        expected to leave the order in the retry queue rather than refund: the
        usual cause is one node being full for an hour, not a lost sale.
    """
    candidates = eligible_nodes(nodes, country_code=country_code)
    if not candidates:
        raise NoCapacityAvailable(
            "No server currently has room for a new account.",
            country_code=country_code,
            considered=len(tuple(nodes)),
        )
    return candidates[0]


__all__ = ["eligible_nodes", "select_node"]
