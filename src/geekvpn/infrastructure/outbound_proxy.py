"""Which outbound calls go through the operator's SOCKS5 proxy.

For a deployment on a server inside Iran. From there, Telegram is unreachable
directly, and the foreign crypto gateways and Google's push service refuse
Iranian addresses, while the Iranian bank gateways *prefer* one and the VPN
panels are reachable either way. So the proxy is a per-host decision, not a
process-wide `HTTPS_PROXY`: an environment variable would also send the bank
gateways abroad, where they fail for the opposite reason.

Installed once at start-up, like the encryption keyring, because the calls it
governs are spread across modules that use `httpx` directly (`httpx.post(...)`)
rather than a shared client. Every such call passes `proxy=proxy_for(url)`.
With no proxy configured that is `None` everywhere, and nothing changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

#: Hosts that cannot be reached from an Iranian address, or that refuse one.
#: Matched with their subdomains. The operator can add more in `.env`
#: (`PROXY__EXTRA_HOSTS`) without a code change.
DEFAULT_HOSTS: Final[tuple[str, ...]] = (
    "api.telegram.org",
    "api.nowpayments.io",
    "api.plisio.net",
    "toncenter.com",
    "fcm.googleapis.com",
    "oauth2.googleapis.com",
)

#: The host aiogram talks to; used to ask whether the bots need the proxy.
TELEGRAM_API: Final = "https://api.telegram.org"


@dataclass(frozen=True, slots=True)
class ProxyPolicy:
    url: str | None = None
    hosts: tuple[str, ...] = DEFAULT_HOSTS

    @classmethod
    def build(cls, url: str, extra_hosts: str = "") -> ProxyPolicy:
        extra = tuple(h.strip().lower() for h in extra_hosts.split(",") if h.strip())
        return cls(url=url.strip() or None, hosts=DEFAULT_HOSTS + extra)

    def for_url(self, url: str) -> str | None:
        if not self.url:
            return None
        host = (urlsplit(url).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in self.hosts):
            return self.url
        return None


_policy = ProxyPolicy()


def install_proxy(policy: ProxyPolicy) -> None:
    global _policy
    _policy = policy


def proxy_for(url: str) -> str | None:
    """The proxy URL for a request to `url`, or `None` to connect directly."""
    return _policy.for_url(url)


__all__ = ["DEFAULT_HOSTS", "TELEGRAM_API", "ProxyPolicy", "install_proxy", "proxy_for"]
