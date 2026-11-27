"""Metrics for a container that runs several uvicorn workers.

Each worker is its own process with its own `MetricsRegistry`, and a scrape is
answered by whichever worker is free. Rendering one worker's registry is
therefore a different, unrelated number on every scrape - 996, then 1147, then
996 - and Prometheus reads each drop as a process restart. ``rate()`` over such
a series measures the workers' lifetime totals rather than recent traffic, so
one old burst of 5xx kept `HighErrorRate` firing with no error in the logs.

So every worker writes its registry's state to ``<directory>/<worker>.json``
every few seconds, and the worker answering a scrape adds the other files to
its own live numbers. What that has to get right:

- **A counter never goes down.** A worker that died keeps its file and its
  counts: the requests it served still happened, and removing them would be a
  drop that reads as a reset. A respawned worker writes a new file under a new
  name rather than overwriting an old one.
- **The write interval is shorter than the scrape interval** (5s against 15s).
  Another worker's file is at most one interval old, so it already holds
  everything that worker had counted by the previous scrape.
- **Gauges are only taken from live workers.** A dead worker's requests in
  flight are not in flight. A file not rewritten for `stale_after` seconds is
  a dead worker's.

The directory should be a tmpfs mounted on the container, so it starts empty
whenever the container does - which is when every counter restarts anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from geekvpn.infrastructure.observability.metrics import Gauge, MetricsRegistry

logger = structlog.stdlib.get_logger(__name__)

#: How often each worker writes its numbers. Below the 15s scrape interval on
#: purpose; see the module docstring.
WRITE_INTERVAL_SECONDS = 5.0
#: A file not rewritten for this long belongs to a worker that has stopped.
STALE_AFTER_SECONDS = 30.0

_SUFFIX = ".json"


class SharedMetrics:
    """One worker's half of the shared directory: it writes its own file and
    reads everyone else's when it answers a scrape."""

    def __init__(
        self,
        registry: MetricsRegistry,
        *,
        directory: Path | str,
        clock: Callable[[], float] = time.time,
        worker_id: str | None = None,
        stale_after_seconds: float = STALE_AFTER_SECONDS,
    ) -> None:
        self._registry = registry
        self._directory = Path(directory)
        self._clock = clock
        # The pid alone is not enough: a respawned worker can be handed an
        # old pid and would overwrite - and lower - a dead worker's counts.
        self._worker_id = worker_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._path = self._directory / f"{self._worker_id}{_SUFFIX}"
        self._stale_after = stale_after_seconds

    @property
    def path(self) -> Path:
        return self._path

    def write(self) -> None:
        """Replace this worker's file with its current numbers, atomically.

        Written to a temporary name and renamed, so a reader never sees half
        a file.
        """
        self._directory.mkdir(parents=True, exist_ok=True)
        payload = {"written_at": self._clock(), "metrics": self._registry.snapshot()}
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self._path)

    def render(self) -> str:
        """This worker's live numbers plus every other worker's last file."""
        return self._registry.render(others=self._others())

    async def run(self, interval_seconds: float = WRITE_INTERVAL_SECONDS) -> None:
        """Write on a timer until cancelled, and once more on the way out."""
        try:
            while True:
                self._write_logged()
                await asyncio.sleep(interval_seconds)
        finally:
            self._write_logged()

    def _write_logged(self) -> None:
        try:
            self.write()
        except OSError:
            # A full or read-only disk must not take the worker down; the
            # scrape just reports this worker's last good file.
            logger.exception("metrics.shared_write_failed", path=str(self._path))

    def _others(self) -> list[dict[str, Any]]:
        now = self._clock()
        others: list[dict[str, Any]] = []
        for path in sorted(self._directory.glob(f"*{_SUFFIX}")):
            if path == self._path:
                continue
            snapshot = _read(path)
            if snapshot is None:
                continue
            metrics: dict[str, Any] = snapshot["metrics"]
            written_at = snapshot.get("written_at")
            live = isinstance(written_at, int | float) and now - written_at <= self._stale_after
            if not live:
                metrics = {
                    name: state
                    for name, state in metrics.items()
                    if not isinstance(self._registry.get(name), Gauge)
                }
            others.append(metrics)
        return others


def _read(path: Path) -> dict[str, Any] | None:
    """A worker's file, or None for one that is missing, torn or not ours."""
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("metrics"), dict):
            return data
    return None


__all__ = ["STALE_AFTER_SECONDS", "WRITE_INTERVAL_SECONDS", "SharedMetrics"]
