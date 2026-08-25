"""Recreating a front-end must be followed by an nginx reload.

The front-end pools are resolved once, when nginx loads its config. That is
what stopped a stale DNS lookup from 502ing the first page load after a quiet
period - and it means a recreated container, which always comes back on a new
address, leaves nginx routing to an address nothing answers on. Not
occasionally: every request, until something restarts the edge.

The reload is therefore not a nicety in the deploy script, it is the other half
of the pools. This checks the two stay together, because the failure they
produce apart looks exactly like the one they were introduced to fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy.sh"
ENTRYPOINT = ROOT / "docker" / "nginx" / "entrypoint.sh"


def test_the_deploy_reloads_nginx_after_starting_the_front_ends() -> None:
    source = DEPLOY.read_text(encoding="utf-8")

    start = source.find("up -d --no-deps miniapp admin")
    assert start != -1, "the deploy no longer starts the front-ends"

    after = source[start:]
    assert "nginx -s reload" in after, (
        "nothing reloads nginx after the front-ends are recreated, so it keeps "
        "routing to the addresses their previous containers had"
    )


def test_the_pools_still_exist_to_need_it() -> None:
    """If the pools go away, so should the reload - and this test."""
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    assert re.search(r"^\s*upstream %s", entrypoint, re.MULTILINE) or "upstream %s" in entrypoint, (
        "the entrypoint no longer writes upstream pools; the reload in "
        "deploy.sh exists only for them"
    )
