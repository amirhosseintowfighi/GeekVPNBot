"""Response models shared by the foundation endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from geekvpn.presentation.api.base_schema import ApiModel


class LivenessResponse(ApiModel):
    status: Literal["alive"] = "alive"
    service: str
    version: str


class DependencyStatus(ApiModel):
    name: str
    healthy: bool
    latency_ms: float
    error: str | None = None


class ReadinessResponse(ApiModel):
    status: Literal["ready", "degraded"]
    dependencies: list[DependencyStatus] = Field(default_factory=list)


class ServiceInfoResponse(ApiModel):
    name: str
    version: str
    environment: str
    api_version: str = "v1"
