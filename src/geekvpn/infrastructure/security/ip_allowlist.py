"""CIDR allowlisting, and the harder half: deciding what the client address is.

The dangerous part of this file is not the matching, it is ``client_ip``. A
header an attacker can write is not evidence. ``X-Forwarded-For`` is appended to
by every proxy in the chain, so the leftmost entry - the one almost every naive
implementation reads - is whatever the *client* chose to send. Reading it to
enforce an admin allowlist means the allowlist can be bypassed with one header,
which is worse than having no allowlist, because it is believed.

The address is therefore counted from the **right**, by the number of proxies we
know are in front of the application.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

FORWARDED_FOR_HEADER: Final = "X-Forwarded-For"
REAL_IP_HEADER: Final = "X-Real-IP"


class AllowlistConfigError(ValueError):
    """An entry in the configured allowlist is not an address or a network."""


def parse_entry(entry: str) -> IpNetwork:
    """Parse one entry. A bare address becomes a single-host network.

    ``strict=False`` so that ``10.0.0.5/24`` is accepted as the /24 it obviously
    means, rather than refusing to boot over host bits an operator left in.
    """
    text = (entry or "").strip()
    if not text:
        raise AllowlistConfigError("Empty allowlist entry.")
    try:
        return ipaddress.ip_network(text, strict=False)
    except ValueError as exc:
        raise AllowlistConfigError(f"{text!r} is not a valid IP address or CIDR range.") from exc


def parse_ip(value: str) -> IpAddress | None:
    """Parse an address, tolerating a ``host:port`` pair and IPv6 brackets."""
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("["):  # [::1]:8080
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:  # 1.2.3.4:5678 - one colon cannot be IPv6
        text = text.split(":", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class IpAllowlist:
    networks: tuple[IpNetwork, ...] = ()

    @classmethod
    def from_entries(cls, entries: Iterable[str]) -> IpAllowlist:
        return cls(tuple(parse_entry(entry) for entry in entries if str(entry).strip()))

    @property
    def is_empty(self) -> bool:
        return not self.networks

    def allows(self, value: str | IpAddress | None) -> bool:
        """Whether this address may proceed.

        An empty allowlist allows everything: the feature is opt-in, and a
        deployment that never configured it must not lock its own operators out
        on upgrade. An address that cannot be parsed is **refused** whenever a
        list is configured - if we cannot tell where a request came from, we
        cannot claim it came from an approved place.
        """
        if self.is_empty:
            return True
        address = parse_ip(value) if isinstance(value, str) or value is None else value
        if address is None:
            return False
        return any(address in network for network in self.networks)


def client_ip(
    *,
    remote_addr: str | None,
    forwarded_for: str | None = None,
    real_ip: str | None = None,
    trusted_proxy_count: int = 0,
) -> str | None:
    """The most trustworthy client address available.

    ``trusted_proxy_count`` is how many proxies we operate between the internet
    and this process - typically 1 for a single nginx, 2 behind a CDN as well.

    * 0 trusted proxies: forwarding headers are ignored entirely. They are
      unauthenticated client input, and with nothing in front of us there is no
      reason for them to exist.
    * n trusted proxies: the interesting entry is the n-th from the right, since
      each of our own proxies appended exactly one entry. Anything further left
      was supplied by the caller and is discarded.

    Returns ``None`` when no usable address can be established, which callers
    must treat as "unknown", never as "allowed".
    """
    if trusted_proxy_count <= 0:
        return str(parse_ip(remote_addr) or "") or None

    chain: Sequence[str] = [
        part.strip() for part in (forwarded_for or "").split(",") if part.strip()
    ]
    if chain:
        # The rightmost entry was added by the proxy nearest to us. With one
        # trusted proxy that entry is the address it saw, i.e. the real client.
        index = len(chain) - trusted_proxy_count
        index = max(index, 0)
        candidate = parse_ip(chain[index])
        if candidate is not None:
            return str(candidate)

    # X-Real-IP carries a single value and is set by our own proxy, so it is
    # only consulted when a chain is unavailable.
    candidate = parse_ip(real_ip)
    if candidate is not None:
        return str(candidate)
    return str(parse_ip(remote_addr) or "") or None


DENIED_MESSAGE_FA: Final = "دسترسی از این نشانی شبکه مجاز نیست."

__all__ = [
    "DENIED_MESSAGE_FA",
    "FORWARDED_FOR_HEADER",
    "REAL_IP_HEADER",
    "AllowlistConfigError",
    "IpAllowlist",
    "client_ip",
    "parse_entry",
    "parse_ip",
]
