"""The plugin registry.

This is the mechanism that makes "adding a panel requires only a new adapter"
literally true. An adapter module declares itself:

    @register_panel(PanelKind.MARZBAN, config=MarzbanConfig)
    class MarzbanAdapter: ...

and nothing else in the codebase changes. No `if kind == ...` chain, no factory
switch, no service-layer edit. `test_registry.py` enforces this by asserting
that the set of registered kinds equals the set of `PanelKind` members, so a
half-wired panel fails the build rather than production.

Why a decorator registry rather than `entry_points`:

- It works identically in a container, in tests, and in a dev shell, with no
  reinstall step after adding a file.
- Registration failures surface at import time, not at first use.
- `entry_points` remains available later for genuinely third-party plugins;
  `load_external_adapters()` below is the seam for that, so choosing this now
  does not close the door.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.panels.enums import Capability, PanelKind

T = TypeVar("T")


class UnknownPanelKind(ValidationError):
    code = "unknown_panel_kind"
    message = "No adapter is registered for that panel type."


class DuplicatePanelKind(ValidationError):
    code = "duplicate_panel_kind"
    message = "Two adapters claim the same panel type."


@dataclass(frozen=True, slots=True)
class PanelPlugin:
    """One registered adapter and everything needed to instantiate it."""

    kind: PanelKind
    adapter_cls: type[Any]
    config_cls: type[Any]
    capabilities: frozenset[Capability]
    description: str = ""


class PanelRegistry:
    """Maps a `PanelKind` to its plugin. One global instance; see `registry`."""

    def __init__(self) -> None:
        self._plugins: dict[PanelKind, PanelPlugin] = {}

    def register(self, plugin: PanelPlugin) -> None:
        existing = self._plugins.get(plugin.kind)
        if existing is not None and existing.adapter_cls is not plugin.adapter_cls:
            raise DuplicatePanelKind(
                f"{plugin.kind.value!r} is already registered to {existing.adapter_cls.__name__}.",
                kind=plugin.kind.value,
            )
        self._plugins[plugin.kind] = plugin

    def get(self, kind: PanelKind | str) -> PanelPlugin:
        """Look a plugin up by kind or by its string value.

        Coercing every key through `PanelKind` would quietly undo the whole point
        of a registry: an out-of-tree adapter registered under its own enum could
        be stored but never retrieved. So a key that is already registered is used
        as-is, and only bare strings are resolved - first against the registered
        members, then against the bundled enum for a helpful error.
        """
        key: Any = kind
        if not isinstance(kind, PanelKind):
            key = next(
                (k for k in self._plugins if k is kind or getattr(k, "value", k) == kind),
                None,
            )
            if key is None:
                try:
                    key = PanelKind(kind)
                except ValueError as exc:
                    raise UnknownPanelKind(
                        f"{kind!r} is not a known panel type.",
                        kind=str(kind),
                        known=sorted(str(getattr(k, "value", k)) for k in self._plugins),
                    ) from exc
        plugin = self._plugins.get(key)
        if plugin is None:
            value = str(getattr(key, "value", key))
            raise UnknownPanelKind(
                f"No adapter registered for {value!r}.",
                kind=value,
                known=sorted(str(getattr(k, "value", k)) for k in self._plugins),
            )
        return plugin

    def __contains__(self, kind: object) -> bool:
        return kind in self._plugins

    def __iter__(self) -> Iterator[PanelPlugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    @property
    def kinds(self) -> frozenset[PanelKind]:
        return frozenset(self._plugins)


#: Process-wide registry.
registry = PanelRegistry()


def register_panel(
    kind: PanelKind,
    *,
    config: type[Any],
    description: str = "",
) -> Callable[[type[T]], type[T]]:
    """Class decorator that publishes an adapter to the registry.

    Capabilities are read off the class rather than passed in, so the
    advertised set can never drift from the implemented one.
    """

    def decorate(cls: type[T]) -> type[T]:
        declared = getattr(cls, "capabilities", None)
        if declared is None:
            raise DuplicatePanelKind(
                f"{cls.__name__} must declare a `capabilities` class attribute."
            )
        registry.register(
            PanelPlugin(
                kind=kind,
                adapter_cls=cls,
                config_cls=config,
                capabilities=frozenset(declared),
                description=description or (cls.__doc__ or "").strip().split("\n")[0],
            )
        )
        return cls

    return decorate


_bundled_loaded = False


def load_bundled_adapters() -> None:
    """Import every module under `.adapters` so decorators run.

    Discovery by walking the package, rather than a hand-written import list,
    is what keeps the "only add a file" promise honest.

    Idempotent by design: callers should never have to know whether somebody
    else already loaded them, and re-running the decorators would raise
    DuplicatePanelKind.
    """
    global _bundled_loaded
    if _bundled_loaded:
        return
    from geekvpn.infrastructure.panels import adapters

    for module in pkgutil.iter_modules(adapters.__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{adapters.__name__}.{module.name}")
    _bundled_loaded = True
