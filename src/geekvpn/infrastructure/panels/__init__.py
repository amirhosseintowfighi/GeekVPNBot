"""Panel plugin infrastructure.

Importing this package registers every bundled adapter as a side effect of
importing `geekvpn.infrastructure.panels.adapters`. That is the only place in
the codebase where the concrete panel list appears, and it exists purely so
that `docker compose up` yields a fully populated registry.
"""

from geekvpn.infrastructure.panels.config import PanelConnectionConfig
from geekvpn.infrastructure.panels.factory import PanelFactory
from geekvpn.infrastructure.panels.registry import (
    PanelRegistry,
    UnknownPanelKind,
    register_panel,
    registry,
)

__all__ = [
    "PanelConnectionConfig",
    "PanelFactory",
    "PanelRegistry",
    "UnknownPanelKind",
    "register_panel",
    "registry",
]
