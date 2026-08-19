"""What can reach what.

`internal: true` on a Docker network does more than block inbound traffic: it
removes the default route and the DNS resolver. A container attached to nothing
else cannot resolve a hostname, let alone open a connection.

That is exactly right for Postgres and Redis, and it was silently fatal for
everything that talks to a third party. The bot sat on `backend` alone, so its
webhook registration failed with

    ClientConnectorDNSError: Cannot connect to host api.telegram.org:443
    ssl:default [Temporary failure in name resolution]

and the bot never received a single Telegram update. The API and the worker
were on the same network, which means the first paid order could not have
reached a VPN panel either - provisioning would have failed for a reason no
log on this side would explain.

None of this is visible from inside the application. The code is right, the
container is healthy, and the symptom reads as the other end being down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]

#: Services that call a third party over the internet, and what they call.
NEEDS_EGRESS: dict[str, str] = {
    "api": "VPN panel adapters, over HTTPS",
    "api_blue": "VPN panel adapters, over HTTPS",
    "api_green": "VPN panel adapters, over HTTPS",
    "bot": "api.telegram.org, to register its webhook and send messages",
    "worker": "VPN panels, draining the provisioning queue",
    "certbot": "Let's Encrypt, to issue and renew the certificate",
}

#: Services that must NOT be able to reach out. A database with a route to the
#: internet is a database that can be exfiltrated through one SQL injection.
MUST_STAY_SEALED: frozenset[str] = frozenset({"postgres", "redis"})


def compose_files() -> list[Path]:
    return sorted(ROOT.glob("docker-compose*.yml"))


def internal_networks() -> set[str]:
    """Every network declared `internal: true` anywhere in the stack."""
    found: set[str] = set()
    for path in compose_files():
        text = path.read_text(encoding="utf-8")
        if "\nnetworks:" not in text:
            continue
        block = text[text.index("\nnetworks:") :]
        current: str | None = None
        for line in block.splitlines():
            named = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
            if named:
                current = named.group(1)
            elif current and re.match(r"^\s+internal:\s*true\s*$", line):
                found.add(current)
    return found


def networks_of(service: str) -> set[str]:
    """Networks the service is attached to, merged across every compose file."""
    attached: set[str] = set()
    for path in compose_files():
        text = path.read_text(encoding="utf-8")
        for block in re.finditer(
            rf"^  {re.escape(service)}:\n(.*?)(?=^  [a-z]|^[a-z])",
            text,
            re.MULTILINE | re.DOTALL,
        ):
            for line in block.group(1).splitlines():
                listed = re.match(r"^\s+networks:\s*\[([^\]]*)\]", line)
                if listed:
                    attached |= {
                        name.strip() for name in listed.group(1).split(",") if name.strip()
                    }
    return attached


def test_the_topology_this_reads_is_still_there() -> None:
    assert internal_networks(), "no internal network found; the topology has changed"
    assert networks_of("postgres"), "postgres declares no networks; re-read this test"


def test_everything_that_calls_out_can_reach_the_internet() -> None:
    internal = internal_networks()

    stranded = [
        f"{service} (needs {reason}) is only on {sorted(networks_of(service))}"
        for service, reason in sorted(NEEDS_EGRESS.items())
        # An empty set means the service inherits its networks from the base
        # file, where the same service is checked on its own.
        if networks_of(service) and networks_of(service) <= internal
    ]

    assert not stranded, (
        "these are attached only to internal networks, so they cannot resolve or "
        "reach anything outside this stack:\n  " + "\n  ".join(stranded)
    )


def test_the_datastores_stay_sealed_in() -> None:
    """The other half of the rule, so widening egress cannot quietly take them
    along: Postgres and Redis have no business reaching the internet."""
    internal = internal_networks()

    exposed = [
        f"{service} is on {sorted(networks_of(service))}"
        for service in sorted(MUST_STAY_SEALED)
        if networks_of(service) and not networks_of(service) <= internal
    ]

    assert not exposed, "these can reach outside this stack and must not:\n  " + "\n  ".join(
        exposed
    )
