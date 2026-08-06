"""Response models shared by the foundation endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"
    service: str
    version: str


class DependencyStatus(BaseModel):
    name: str
    healthy: bool
    latency_ms: float
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    dependencies: list[DependencyStatus] = Field(default_factory=list)


class ServiceInfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    api_version: str = "v1"
