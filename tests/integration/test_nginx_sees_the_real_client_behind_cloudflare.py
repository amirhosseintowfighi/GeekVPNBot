"""Behind Cloudflare, nginx must key on the visitor, not on Cloudflare.

Every request through a proxied Cloudflare domain arrives from a Cloudflare
address. Without the real-IP rewrite, the per-IP rate limits would throttle all
customers as a handful of clients, and `ADMIN_ALLOW_CIDRS` would refuse the
operator. The rewrite is only safe while `CF-Connecting-IP` is believed from
Cloudflare's ranges alone - from anywhere else it is a header a visitor writes.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

NGINX = Path(__file__).resolve().parents[2] / "docker" / "nginx"
SNIPPET = NGINX / "snippets" / "cloudflare-real-ip.conf"


def _trusted() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [
        ipaddress.ip_network(m)
        for m in re.findall(r"^set_real_ip_from\s+(\S+);", SNIPPET.read_text(), re.M)
    ]


def test_the_rewrite_runs_before_the_rate_limits_key_on_the_address() -> None:
    conf = NGINX.joinpath("nginx.conf").read_text()

    included = conf.index("include /etc/nginx/snippets/cloudflare-real-ip.conf;")
    assert included < conf.index("limit_req_zone")


def test_the_header_is_cloudflares_own() -> None:
    assert re.search(r"^real_ip_header\s+CF-Connecting-IP;", SNIPPET.read_text(), re.M)


def test_only_cloudflare_is_trusted_to_name_the_client() -> None:
    trusted = _trusted()

    assert trusted, "no trusted ranges: the header would never be believed"
    for network in trusted:
        # Anything this wide would let a direct visitor forge their address.
        assert network.prefixlen >= (12 if network.version == 4 else 29), network
        assert not network.is_private, network


def test_the_rewrite_is_not_recursive() -> None:
    # `real_ip_recursive on` walks X-Forwarded-For style lists; with a single
    # header set by Cloudflare it only widens what a client can influence.
    assert "real_ip_recursive" not in SNIPPET.read_text()
