"""Every `resolver` nginx uses must be Docker's own DNS, and only that.

The API colours are proxied through a variable (`$active_api`), so nginx
resolves `api_blue` / `api_green` at request time with whichever resolver is
in scope. The TLS snippet once listed `127.0.0.11 1.1.1.1`, and being included
in every HTTPS server block it overrode the http-level resolver there. Nginx
round-robins between listed servers, so some lookups went to Cloudflare, which
has never heard of `api_blue`, and the "Host not found" was cached for the
resolver's `valid` period. Payment callbacks and API calls then answered 502
at random. The deploy's own edge check runs on port 80, which does not include
the snippet, so it passed throughout.

Docker's resolver forwards external names itself, so OCSP stapling loses
nothing by using it alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

NGINX = Path(__file__).resolve().parents[2] / "docker" / "nginx"
DOCKER_DNS = "127.0.0.11"
RESOLVER = re.compile(r"^\s*resolver\s+([^;]+);", re.MULTILINE)


def _resolvers() -> list[tuple[str, list[str]]]:
    found = []
    for path in sorted(NGINX.rglob("*")):
        if path.is_file() and (path.suffix == ".conf" or path.parent.name == "snippets"):
            for match in RESOLVER.finditer(path.read_text()):
                servers = [arg for arg in match.group(1).split() if "=" not in arg]
                found.append((str(path.relative_to(NGINX)), servers))
    return found


def test_there_is_a_resolver_to_check() -> None:
    assert _resolvers(), "no resolver directive found; the test is looking in the wrong place"


@pytest.mark.parametrize(("where", "servers"), _resolvers(), ids=lambda v: str(v))
def test_the_resolver_is_docker_dns_alone(where: str, servers: list[str]) -> None:
    assert servers == [DOCKER_DNS], f"{where} resolves through {servers}"
