"""Adopting an account that was sold outside the bot.

A customer buys through support, gets a subscription link in a chat, and from
then on has no way to see how much traffic is left or when it expires - the bot
only knows about services it sold. This asks every panel whether the link they
pasted names a real account, and if it does, records it as theirs.

Two rules do most of the work here.

**The panel is the authority, never the customer.** Expiry, quota and usage are
read back from the account itself, so a pasted link cannot conjure a service
with better terms than the one it points at.

**A claim is not a transfer.** An account already recorded against somebody is
refused rather than moved. The link is a bearer token: anybody who has seen it
once - in a forwarded message, over a support operator's shoulder - could
otherwise take a stranger's service by pasting it, and the real owner would
find out when it stopped working.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import timedelta

import structlog

from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.ports import (
    NodeRepository,
    PanelProvider,
    SubscriptionRepository,
)
from geekvpn.application.provisioning.usage_sync import BYTES_PER_MIB
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.panels.values import PanelAccount
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.domain.provisioning.subscription import Subscription

logger = structlog.stdlib.get_logger(__name__)

#: An account whose panel reports no expiry still needs one, because the column
#: is not nullable and every screen renders a date. A year is long enough not to
#: nag a customer about a service that has no end, and short enough that the row
#: is revisited rather than trusted forever.
UNKNOWN_EXPIRY_DAYS = 365


class ClaimOutcome(enum.StrEnum):
    """Why a claim did or did not work.

    An enum rather than an exception per case: none of these are faults, they
    are the four ordinary answers, and the bot turns each into a sentence.
    """

    CLAIMED = "claimed"
    #: No panel we own has an account behind that link.
    NOT_FOUND = "not_found"
    #: Found, but already recorded - possibly against this very customer.
    ALREADY_CLAIMED = "already_claimed"
    #: Every panel refused to answer. Distinct from NOT_FOUND on purpose:
    #: telling somebody their real service does not exist because a panel was
    #: down is the one wrong answer here.
    PANEL_UNREACHABLE = "panel_unreachable"


@dataclass(frozen=True, slots=True)
class ClaimResult:
    outcome: ClaimOutcome
    subscription: Subscription | None = None


class ClaimService:
    def __init__(
        self,
        *,
        subscriptions: SubscriptionRepository,
        nodes: NodeRepository,
        panels: PanelProvider,
        clock: Clock,
    ) -> None:
        self._subscriptions = subscriptions
        self._nodes = nodes
        self._panels = panels
        self._clock = clock

    async def claim(
        self, *, url: str, user_id: int, reseller_id: str | None = None
    ) -> ClaimResult:
        """Find the account behind `url` and record it as this customer's."""
        cleaned = url.strip()
        if not cleaned:
            return ClaimResult(ClaimOutcome.NOT_FOUND)

        located, every_panel_failed = await self._search(cleaned)
        if located is None:
            # "Nowhere" and "nobody answered" are different sentences. Telling
            # somebody holding a working link that their service does not exist
            # because a panel was down is the one wrong answer here.
            return ClaimResult(
                ClaimOutcome.PANEL_UNREACHABLE if every_panel_failed else ClaimOutcome.NOT_FOUND
            )

        node_id, account = located
        if await self._already_known(node_id, account):
            return ClaimResult(ClaimOutcome.ALREADY_CLAIMED)

        subscription = self._build(
            node_id=node_id, account=account, user_id=user_id, reseller_id=reseller_id
        )
        await self._subscriptions.add(subscription)
        return ClaimResult(ClaimOutcome.CLAIMED, subscription)

    async def _search(self, url: str) -> tuple[tuple[str, PanelAccount] | None, bool]:
        """Ask each node in turn, and say whether every one of them failed.

        A panel that raises is skipped rather than fatal - one dead node must
        not hide an account living on another - but if *every* node raised we
        have learnt nothing, and the caller needs to know that rather than
        report an empty search.
        """
        asked = 0
        failed = 0
        # Every node, not the sellable ones. The account we are looking for
        # already exists, and it does not move because we stopped selling
        # from the server it lives on.
        for node in await self._nodes.list_every():
            asked += 1
            try:
                adapter = await self._panels.for_node(node)
                account = await adapter.find_by_subscription(url)
            except PanelError as exc:
                # Named, because a claim that fails on every node looks
                # identical to a link that was never real - and only one of
                # those is the customer's problem.
                logger.warning(
                    "claim.panel_refused",
                    node_id=node.id,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failed += 1
                continue
            if account is not None:
                return (node.id, account), False
        return None, bool(asked) and failed == asked

    async def _already_known(self, node_id: str, account: PanelAccount) -> bool:
        """Is this panel account already somebody's service here?

        Matched on the remote username within the node, which is what the panel
        itself keys on - not on the link, which can be rotated.
        """
        existing, _ = await self._subscriptions.search(node_id=node_id, limit=1000, offset=0)
        return any(s.remote_username == account.ref.username for s in existing)

    def _build(
        self,
        *,
        node_id: str,
        account: PanelAccount,
        user_id: int,
        reseller_id: str | None,
    ) -> Subscription:
        now = self._clock.now()
        expires_at = account.expires_at or now + timedelta(days=UNKNOWN_EXPIRY_DAYS)
        # A panel can report an account that already lapsed. Recording it as
        # ACTIVE would show the customer a working service and then fail to
        # connect; the expiry sweep would fix it within the hour, but the first
        # thing they saw would have been wrong.
        started_at = min(now, expires_at - timedelta(minutes=1))
        quota = account.usage.quota
        state = (
            SubscriptionState.ACTIVE if expires_at > now else SubscriptionState.EXPIRED
        )
        return Subscription(
            str(uuid.uuid4()),
            user_id=user_id,
            # No order and no plan: nobody bought this here. See migration
            # 0022 for why we do not invent one.
            order_id=None,
            plan_id=None,
            started_at=started_at,
            expires_at=expires_at,
            remote_username=account.ref.username,
            state=state,
            node_id=node_id,
            remote_id=account.ref.external_id,
            reseller_id=reseller_id,
            subscription_url=account.subscription_url,
            traffic_limit_mib=(
                None
                if quota.is_unlimited or quota.total_bytes is None
                else quota.total_bytes // BYTES_PER_MIB
            ),
            traffic_used_mib=account.usage.used_bytes // BYTES_PER_MIB,
            last_synced_at=account.usage.measured_at,
        )


__all__ = [
    "UNKNOWN_EXPIRY_DAYS",
    "ClaimOutcome",
    "ClaimResult",
    "ClaimService",
]
