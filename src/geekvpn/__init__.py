"""Geek VPN.

The single source of truth for the application version.

Read from installed package metadata rather than hard-coded, so pyproject.toml is
the only place a release number is written. Three files previously carried three
different literals (0.1.0, 0.2.0, 0.3.0) and every one of them was reported to a
different consumer: the health endpoint, the OpenAPI document, and the build_info
metric that drives the deploy annotation on the Grafana dashboard.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("geekvpn")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    # Running without an install (a bare PYTHONPATH, as in some test harnesses).
    # Reporting "0.0.0+unknown" is honest; inventing a number is not.
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
