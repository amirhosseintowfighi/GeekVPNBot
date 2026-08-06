"""Dependency-free container healthcheck.

Used by Docker HEALTHCHECK so the runtime image does not need curl or wget
installed - one fewer package, one fewer CVE.

Usage: ``python -m geekvpn.entrypoints.healthcheck http://localhost:8000/health/live``
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 5


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 2
    url = argv[1]
    if not url.startswith(("http://localhost", "http://127.0.0.1")):
        return 2  # only ever probe ourselves
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return 0 if 200 <= response.status < 300 else 1
    except (urllib.error.URLError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
