"""Per-panel connection configuration.

Each adapter ships its own config model. The registry stores the class, so
validating an operator-supplied panel record is `plugin.config_cls(**payload)`
with no knowledge of which panel it is.

Credentials are `SecretStr` so that a stray log line or a `repr()` in a
traceback cannot leak a panel password into the log aggregator.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic.alias_generators import to_camel


class PanelConnectionConfig(BaseModel):
    """Fields common to every HTTP-based panel.

    Accepts both spellings of every field. The operator-supplied part of a
    node's config arrives from the admin panel, which speaks camelCase like the
    rest of the API, and is stored verbatim - so a PasarGuard node with a group
    selected was saved holding `defaultGroups`, which `extra="forbid"` then
    rejected on the way back in. Building the adapter raised, and because that
    is a ValidationError rather than a PanelError nothing caught it: every
    operation on that node failed, and the usage sweep took the whole worker
    tick down with it.

    `populate_by_name` keeps the snake_case spelling working, so rows written
    by any other path stay valid and no data migration is needed.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )

    base_url: str = Field(description="Root URL of the panel, e.g. https://panel.example.com")
    username: str = ""
    password: SecretStr = SecretStr("")
    verify_tls: bool = True
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    #: Total attempts for a retryable failure, including the first.
    max_attempts: int = Field(default=3, ge=1, le=6)

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return value


class PasarGuardConfig(PanelConnectionConfig):
    """PasarGuard V5."""

    #: Groups to attach new accounts to (PasarGuard's access-grouping concept).
    default_groups: tuple[str, ...] = ()


class MarzbanConfig(PanelConnectionConfig):
    """Marzban."""

    #: Inbound tags per protocol, e.g. {"vless": ("VLESS_TCP",)}; empty means
    #: "whatever the panel defaults to". This is a mapping rather than a flat
    #: list because Marzban keys inbounds by protocol and silently ignores a
    #: flat list, which looks like a successful create that grants no access.
    default_inbounds: dict[str, tuple[str, ...]] = {}


class MarzneshinConfig(PanelConnectionConfig):
    """Marzneshin. Access is granted through *services*, not inbounds."""

    service_ids: tuple[int, ...] = ()


class XuiFamilyConfig(PanelConnectionConfig):
    """Shared shape for the 3x-ui / x-ui lineage.

    These panels nest clients inside an inbound, so an inbound id is mandatory:
    there is no such thing as a free-floating user.
    """

    inbound_id: int = Field(description="Inbound that new clients are added to")
    #: 3x-ui installs behind a random base path, e.g. https://host:2053/AbCdEf
    web_base_path: str = ""

    @field_validator("web_base_path")
    @classmethod
    def _normalise_path(cls, value: str) -> str:
        value = value.strip().strip("/")
        return f"/{value}" if value else ""


class SanaeiConfig(XuiFamilyConfig):
    """MHSanaei 3x-ui."""


class AlirezaConfig(XuiFamilyConfig):
    """alireza0 x-ui."""
