"""alireza0 x-ui adapter.

The older lineage. Functionally the same client-inside-inbound model as 3x-ui,
but it serves the API from the legacy `/xui/API/inbounds` prefix.

If this fork later diverges in behaviour rather than just in routing, the fix
is to override the one affected method here - not to add a branch to the shared
base.
"""

from __future__ import annotations

from typing import ClassVar

from geekvpn.domain.panels.enums import PanelKind
from geekvpn.infrastructure.panels.adapters._xui_base import XuiFamilyAdapter
from geekvpn.infrastructure.panels.config import AlirezaConfig
from geekvpn.infrastructure.panels.registry import register_panel


@register_panel(
    PanelKind.ALIREZA,
    config=AlirezaConfig,
    description="alireza0 x-ui panel.",
)
class AlirezaAdapter(XuiFamilyAdapter):
    """Adapter for x-ui."""

    kind: ClassVar[PanelKind] = PanelKind.ALIREZA
    login_path: ClassVar[str] = "/login"
    api_prefix: ClassVar[str] = "/xui/API/inbounds"

    _config: AlirezaConfig
