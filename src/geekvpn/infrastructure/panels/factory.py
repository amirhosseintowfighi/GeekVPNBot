"""Turning a stored panel record into a live adapter.

The factory is ~30 lines and contains no panel names. That is the measurable
proof that the plugin architecture works: `build()` is written once and is
unchanged by adding a sixth, seventh or twentieth panel.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.panels.enums import PanelKind
from geekvpn.infrastructure.panels.http import PanelHttpClient
from geekvpn.infrastructure.panels.registry import (
    PanelRegistry,
    load_bundled_adapters,
)
from geekvpn.infrastructure.panels.registry import (
    registry as default_registry,
)


class PanelFactory:
    """Builds adapters from operator-supplied configuration."""

    def __init__(self, *, panel_registry: PanelRegistry | None = None) -> None:
        # Only the tests ever called load_bundled_adapters(), so in production the
        # shared registry was empty and every build() raised UnknownPanelKind for
        # a perfectly valid panel. Loading here keeps the plugin discovery story
        # intact while making the factory usable on its own; an injected registry
        # is left untouched, because a caller supplying one is choosing its
        # contents deliberately.
        if panel_registry is None:
            load_bundled_adapters()
        self._registry = panel_registry or default_registry

    def validate_config(self, kind: PanelKind | str, payload: Mapping[str, Any]) -> Any:
        """Validate a config payload against the adapter's own model.

        Used by the admin panel to check a panel's settings before saving,
        rather than discovering they are wrong during a customer's purchase.
        """
        plugin = self._registry.get(kind)
        try:
            return plugin.config_cls(**payload)
        except PydanticValidationError as exc:
            raise ValidationError(
                "The panel configuration is invalid.",
                kind=str(kind),
                errors=exc.errors(include_url=False),
            ) from exc

    def build(
        self,
        kind: PanelKind | str,
        payload: Mapping[str, Any],
        *,
        panel_id: uuid.UUID,
        transport: Any = None,
    ) -> Any:
        """Instantiate the adapter for `kind`. Contains no panel-specific logic."""
        plugin = self._registry.get(kind)
        config = self.validate_config(kind, payload)
        client = PanelHttpClient(
            base_url=config.base_url,
            panel_name=plugin.kind.value,
            timeout_seconds=config.timeout_seconds,
            max_attempts=config.max_attempts,
            verify_tls=config.verify_tls,
            transport=transport,
        )
        return plugin.adapter_cls(config=config, client=client, panel_id=panel_id)
