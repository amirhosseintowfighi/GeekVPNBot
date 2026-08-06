"""Readiness probes.

A probe answers one question: is this dependency usable right now? It must
never raise; a failure is a result, not an exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    healthy: bool
    latency_ms: float
    error: str | None = None


@runtime_checkable
class HealthProbe(Protocol):
    name: str

    async def check(self) -> ProbeResult: ...
