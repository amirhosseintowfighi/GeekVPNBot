"""Rebecca adapter.

Rebecca is a fork of Marzban that kept Marzban's API - the same token grant,
the same `/api/user` resources, the same units - so the whole adapter is a
declaration that it is one. Should it diverge, this class is where the
difference goes; until then a second implementation would be a second place
for the same bug.
"""

from __future__ import annotations

from typing import ClassVar

from geekvpn.domain.panels.enums import PanelKind
from geekvpn.infrastructure.panels.adapters.marzban import MarzbanAdapter
from geekvpn.infrastructure.panels.config import RebeccaConfig
from geekvpn.infrastructure.panels.registry import register_panel


@register_panel(
    PanelKind.REBECCA,
    config=RebeccaConfig,
    description="Rebecca panel (a Marzban fork with the same API).",
)
class RebeccaAdapter(MarzbanAdapter):
    """Adapter for Rebecca."""

    kind: ClassVar[PanelKind] = PanelKind.REBECCA

    _config: RebeccaConfig
