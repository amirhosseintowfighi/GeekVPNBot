"""MHSanaei 3x-ui adapter.

The modern fork of the x-ui family. Serves its API under `/panel/api/inbounds`
and, since v2, publishes an OpenAPI document at `/panel/api/openapi.json`.

The entire adapter is a declaration of two paths, because all real behaviour
is shared with `XuiFamilyAdapter`. That is the intended shape: a fork should
cost a handful of lines, not a reimplementation.
"""

from __future__ import annotations

from typing import ClassVar

from geekvpn.domain.panels.enums import PanelKind
from geekvpn.infrastructure.panels.adapters._xui_base import XuiFamilyAdapter
from geekvpn.infrastructure.panels.config import SanaeiConfig
from geekvpn.infrastructure.panels.registry import register_panel


@register_panel(
    PanelKind.SANAEI,
    config=SanaeiConfig,
    description="MHSanaei 3x-ui panel.",
)
class SanaeiAdapter(XuiFamilyAdapter):
    """Adapter for 3x-ui."""

    kind: ClassVar[PanelKind] = PanelKind.SANAEI
    login_path: ClassVar[str] = "/login"
    api_prefix: ClassVar[str] = "/panel/api/inbounds"

    _config: SanaeiConfig
