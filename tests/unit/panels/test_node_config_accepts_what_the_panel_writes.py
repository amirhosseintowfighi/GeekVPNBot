"""A node config saved by the admin panel can be read back.

The operator-supplied half of a node's config is stored verbatim as JSON, and
the admin panel speaks camelCase like the rest of the API. So selecting a group
on a PasarGuard server wrote `defaultGroups`, the config model wanted
`default_groups`, and `extra="forbid"` rejected it on the way back in.

The consequence was not a bad error message. Building the adapter raised, that
raise is a `ValidationError` rather than a `PanelError` so nothing caught it,
and the usage sweep took the entire worker tick down with it - provisioning
drain and expiry sweep included. Choosing a group in a dropdown disabled every
scheduled job on the platform.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from geekvpn.domain.base.errors import ValidationError
from geekvpn.infrastructure.panels.config import (
    MarzbanConfig,
    MarzneshinConfig,
    PasarGuardConfig,
    XuiFamilyConfig,
)
from geekvpn.infrastructure.panels.factory import PanelFactory

pytestmark = pytest.mark.unit

URL = "https://panel.example.com"


def test_the_exact_payload_that_broke_production():
    """`{"defaultGroups": ["1"]}`, as written by the server dialog."""
    config = PasarGuardConfig(base_url=URL, **{"defaultGroups": ["1"]})

    assert config.default_groups == ("1",)


def test_the_snake_case_spelling_still_works():
    """Rows written by any other path must stay valid - the alternative to this
    was a data migration over everybody's stored configs."""
    config = PasarGuardConfig(base_url=URL, **{"default_groups": ["1"]})

    assert config.default_groups == ("1",)


@pytest.mark.parametrize(
    ("model", "payload", "field", "expected"),
    [
        (MarzbanConfig, {"defaultInbounds": {"vless": ["A"]}}, "default_inbounds", {"vless": ("A",)}),
        (MarzneshinConfig, {"serviceIds": [1, 2]}, "service_ids", (1, 2)),
        (XuiFamilyConfig, {"inboundId": 3}, "inbound_id", 3),
    ],
)
def test_every_panel_accepts_what_the_admin_panel_sends(model, payload, field, expected):
    """PasarGuard is the one that was noticed. Each of these has a camelCase
    field the same dialog could write."""
    assert getattr(model(base_url=URL, **payload), field) == expected


def test_the_shared_connection_fields_too():
    config = PasarGuardConfig(
        **{"baseUrl": URL, "verifyTls": False, "timeoutSeconds": 5, "maxAttempts": 2}
    )

    assert config.verify_tls is False
    assert config.max_attempts == 2


def test_a_key_nobody_recognises_is_still_refused():
    """`extra="forbid"` is doing real work: a typo in a config that silently
    did nothing would be a server quietly granting the wrong access."""
    with pytest.raises(PydanticValidationError):
        PasarGuardConfig(base_url=URL, **{"defualtGroups": ["1"]})


def test_the_factory_builds_the_node_that_used_to_fail():
    """End to end through the path the worker actually takes."""
    factory = PanelFactory()

    config = factory.validate_config(
        "pasarguard",
        {
            "base_url": URL,
            "username": "admin",
            "password": "secret",
            "verify_tls": True,
            "timeout_seconds": 15.0,
            "defaultGroups": ["1"],
        },
    )

    assert config.default_groups == ("1",)


def test_a_genuinely_invalid_config_is_still_reported_as_one():
    factory = PanelFactory()

    with pytest.raises(ValidationError):
        factory.validate_config("pasarguard", {"base_url": "not-a-url"})
