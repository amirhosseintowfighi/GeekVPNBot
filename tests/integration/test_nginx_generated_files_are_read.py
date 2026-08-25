"""Anything the entrypoint generates must be included by something.

`nginx.conf` names the files it includes one by one rather than globbing
`conf.d/*.conf`, and for good reasons written down beside the list: two files
in that directory are fragments the template includes itself, inside a server
block, and pulling them in at http level was fatal in one case and silently
locked the whole edge to the admin allowlist in the other.

The cost is that a new generated file is included by nothing until someone
adds it to that list. `10-frontend-pools.conf` was written correctly at every
container start and read by nobody, so the pool name in `proxy_pass` matched no
upstream group, nginx fell back to treating it as a hostname, and every request
to both front-ends 502ed on a lookup that could never succeed.

This is the project's oldest failure shape - written, correct, and unreachable -
so it is checked rather than remembered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

NGINX = Path(__file__).resolve().parents[2] / "docker" / "nginx"
ENTRYPOINT = NGINX / "entrypoint.sh"
CONF = NGINX / "nginx.conf"
TEMPLATE = NGINX / "templates" / "geekvpn.conf"


def _generated() -> set[str]:
    """conf.d paths the entrypoint writes to."""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    return set(re.findall(r"=(/etc/nginx/conf\.d/[\w.-]+)", source))


def _included() -> set[str]:
    text = CONF.read_text(encoding="utf-8") + TEMPLATE.read_text(encoding="utf-8")
    return set(re.findall(r"include\s+(/etc/nginx/conf\.d/[\w.-]+);", text))


def test_the_entrypoint_generates_something() -> None:
    assert _generated()


def test_every_generated_file_is_included_somewhere() -> None:
    orphans = _generated() - _included()

    assert not orphans, (
        f"generated at container start and read by nothing: {sorted(orphans)}. "
        "Name it in nginx.conf's include list, or in the template if it is a "
        "fragment that belongs inside a server block."
    )


def test_the_pools_file_is_included_at_http_level() -> None:
    """An `upstream` block is only legal there.

    Being included *somewhere* is not enough: the two other generated files are
    fragments the template pulls in inside a server block, and an upstream in
    that position does not parse.
    """
    pools = "/etc/nginx/conf.d/10-frontend-pools.conf"
    assert pools in _generated(), "the entrypoint no longer writes the pools file"

    conf = CONF.read_text(encoding="utf-8")
    assert f"include {pools};" in conf, (
        "the pools file must be named in nginx.conf, not only in the template"
    )
