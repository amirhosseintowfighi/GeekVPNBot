"""Nginx must be allowed to open what it is configured to serve.

`worker_connections 2048` with a soft limit of 1024 descriptors is not a
configuration, it is a wish. A proxied request holds two descriptors - client
and upstream - so the real ceiling was under 500 concurrent connections, and
nginx said so on every single start:

    2048 worker_connections exceed open file resource limit: 1024

The pages that hit it first are the two front-ends, because a Next.js page
loads dozens of chunks at once, while the API sits beside them answering
normally on a handful of requests. Which is exactly what a 502 on the Mini App
and the admin panel, and nowhere else, looks like.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = ROOT / "docker" / "nginx" / "nginx.conf"
COMPOSE = ROOT / "docker-compose.prod.yml"


def _directive(name: str, source: str) -> int:
    match = re.search(rf"^\s*{name}\s+(\d+);", source, re.MULTILINE)
    assert match, f"{name} is not set in nginx.conf"
    return int(match.group(1))


def test_the_descriptor_limit_covers_every_connection_twice() -> None:
    """Two per proxied request, plus listeners, logs and the resolver."""
    source = NGINX_CONF.read_text(encoding="utf-8")
    connections = _directive("worker_connections", source)
    descriptors = _directive("worker_rlimit_nofile", source)

    assert descriptors >= connections * 2, (
        f"{connections} connections need at least {connections * 2} descriptors, "
        f"but nginx is only allowed {descriptors}"
    )


def test_the_container_allows_what_nginx_asks_for() -> None:
    """`worker_rlimit_nofile` raises the soft limit only as far as the hard one."""
    source = NGINX_CONF.read_text(encoding="utf-8")
    descriptors = _directive("worker_rlimit_nofile", source)

    match = re.search(r"nofile:\s*\n\s*soft:\s*(\d+)\s*\n\s*hard:\s*(\d+)", COMPOSE.read_text(encoding="utf-8"))
    assert match, "the nginx service sets no nofile ulimit"
    soft, hard = int(match.group(1)), int(match.group(2))

    assert soft >= descriptors
    assert hard >= descriptors
