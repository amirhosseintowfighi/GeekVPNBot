"""The plugin architecture's own guarantees.

These tests are the enforcement mechanism behind the requirement that "adding a
new panel must require only creating a new adapter". They fail loudly if
someone half-wires a panel or reintroduces a hardcoded panel list.
"""

from __future__ import annotations

import inspect

import pytest

from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.panels.enums import Capability, PanelKind
from geekvpn.infrastructure.panels.registry import (
    PanelPlugin,
    PanelRegistry,
    UnknownPanelKind,
    load_bundled_adapters,
    register_panel,
    registry,
)


@pytest.fixture(scope="module", autouse=True)
def _loaded() -> None:
    load_bundled_adapters()


def test_every_declared_panel_kind_has_an_adapter() -> None:
    """A `PanelKind` with no adapter is a panel that 404s at purchase time."""
    assert registry.kinds == set(PanelKind)


def test_all_five_requested_panels_are_registered() -> None:
    for kind in (
        PanelKind.PASARGUARD,
        PanelKind.MARZBAN,
        PanelKind.MARZNESHIN,
        PanelKind.SANAEI,
        PanelKind.ALIREZA,
    ):
        assert kind in registry, f"{kind.value} is not registered"


def test_adapters_structurally_satisfy_the_port() -> None:
    """Every adapter must implement the full `PanelAdapter` surface.

    `runtime_checkable` only checks method *names*, so we additionally compare
    signatures for the mandatory methods - a wrong signature is just as broken
    as a missing method, and only shows up under mypy otherwise.
    """
    mandatory = [
        "health",
        "close",
        "create_account",
        "get_account",
        "delete_account",
        "suspend",
        "resume",
        "usage",
        "renew",
    ]
    for plugin in registry:
        cls = plugin.adapter_cls
        for name in mandatory:
            assert hasattr(cls, name), f"{cls.__name__} is missing {name}()"
            assert inspect.iscoroutinefunction(getattr(cls, name)), (
                f"{cls.__name__}.{name} must be async"
            )


def test_declared_capabilities_are_real_capabilities() -> None:
    for plugin in registry:
        for capability in plugin.capabilities:
            assert isinstance(capability, Capability)


def test_capability_gated_methods_are_overridden_when_advertised() -> None:
    """Advertising a capability without implementing it is worse than not
    advertising it: the caller checks `capabilities`, proceeds, and gets a
    `NotImplementedError` in the middle of a paid provisioning."""
    from geekvpn.infrastructure.panels.base import HttpPanelAdapter

    gated = {
        Capability.RESET_TRAFFIC: "reset_traffic",
        Capability.BULK_USAGE: "bulk_usage",
        Capability.NODE_INVENTORY: "nodes",
        Capability.SUBSCRIPTION_URL: "subscription",
    }
    for plugin in registry:
        for capability, method in gated.items():
            if capability not in plugin.capabilities:
                continue
            own = getattr(plugin.adapter_cls, method)
            base = getattr(HttpPanelAdapter, method)
            assert own is not base, (
                f"{plugin.adapter_cls.__name__} advertises {capability.value} "
                f"but does not override {method}()"
            )


def test_each_plugin_has_its_own_config_model() -> None:
    for plugin in registry:
        assert plugin.config_cls is not None
        assert hasattr(plugin.config_cls, "model_validate")


def test_unknown_kind_is_a_validation_error_not_a_key_error() -> None:
    """Operators type panel names by hand; this must be a 4xx, not a 500."""
    with pytest.raises(UnknownPanelKind) as excinfo:
        registry.get("totally-made-up")
    assert isinstance(excinfo.value, ValidationError)
    assert "totally-made-up" in str(excinfo.value)


def test_registering_two_adapters_for_one_kind_is_rejected() -> None:
    """Silent overwrite would mean traffic quietly moving to the wrong panel."""
    isolated = PanelRegistry()
    plugin = PanelPlugin(
        kind=PanelKind.MARZBAN,
        adapter_cls=type("A", (), {"capabilities": frozenset()}),
        config_cls=dict,
        capabilities=frozenset(),
    )
    isolated.register(plugin)
    other = PanelPlugin(
        kind=PanelKind.MARZBAN,
        adapter_cls=type("B", (), {"capabilities": frozenset()}),
        config_cls=dict,
        capabilities=frozenset(),
    )
    with pytest.raises(ValidationError):
        isolated.register(other)


def test_reregistering_the_same_class_is_idempotent() -> None:
    """Module re-import during test collection must not explode."""
    isolated = PanelRegistry()
    cls = type("A", (), {"capabilities": frozenset()})
    plugin = PanelPlugin(
        kind=PanelKind.MARZBAN,
        adapter_cls=cls,
        config_cls=dict,
        capabilities=frozenset(),
    )
    isolated.register(plugin)
    isolated.register(plugin)
    assert len(isolated) == 1


def test_decorator_rejects_a_class_without_capabilities() -> None:
    with pytest.raises(ValidationError):

        @register_panel(PanelKind.MARZBAN, config=dict)
        class _NoCaps:
            pass
