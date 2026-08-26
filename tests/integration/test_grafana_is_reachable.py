"""Grafana was configured to be served at an address nothing served.

`GF_SERVER_ROOT_URL` has always said `https://<admin>/grafana/`, and there was
no such route - nor could there have been, because Grafana sat on the
`monitoring` network alone and nginx is on `backend`. An operator following the
address in the config found nothing at the other end.

Both halves are checked here: something has to route to it, and it has to be
reachable from the thing doing the routing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "docker" / "nginx" / "templates" / "geekvpn.conf"
NGINX_CONF = ROOT / "docker" / "nginx" / "nginx.conf"
MONITORING = ROOT / "docker-compose.monitoring.yml"
PROD = ROOT / "docker-compose.prod.yml"


class _Loader(yaml.SafeLoader):
    """Compose's own tags are not YAML the parser knows."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.SequenceNode)
    else loader.construct_scalar(node),
)


def _services(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)["services"]  # noqa: S506


def test_the_edge_routes_to_it() -> None:
    assert "location /grafana/" in TEMPLATE.read_text(encoding="utf-8")


def test_the_edge_can_reach_it() -> None:
    """A route to a container on a network nginx is not on resolves to nothing."""
    grafana = set(_services(MONITORING)["grafana"]["networks"])
    nginx = set(_services(PROD)["nginx"]["networks"])

    assert grafana & nginx, (
        f"grafana is on {sorted(grafana)} and nginx on {sorted(nginx)}; they "
        "share no network, so the route cannot connect"
    )


def test_the_root_url_matches_the_route() -> None:
    """Grafana rewrites its own links from this; a mismatch breaks every one."""
    environment = _services(MONITORING)["grafana"]["environment"]

    assert environment["GF_SERVER_ROOT_URL"].rstrip("/").endswith("/grafana")
    assert environment["GF_SERVER_SERVE_FROM_SUB_PATH"] == "true"


def test_websocket_upgrades_are_mapped() -> None:
    """Live panels hang at "connecting" without it, which reads as broken."""
    assert re.search(r"map \$http_upgrade \$connection_upgrade", NGINX_CONF.read_text(encoding="utf-8"))


def test_it_is_not_a_second_front_door() -> None:
    """No published port: it inherits the admin host's allowlist instead of
    carrying its own password to forget about."""
    assert "ports" not in _services(MONITORING)["grafana"]
