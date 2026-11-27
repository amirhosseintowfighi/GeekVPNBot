"""`/metrics` answers for the whole container when `APP__METRICS_DIR` is set.

The adding-up itself is in `tests/unit/observability/test_metrics_across_workers.py`.
This pins the wiring: the app builds its share from the setting, the endpoint
renders through it, the lifespan writes this worker's file, and without the
setting the endpoint is this process alone, as it always was.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.infrastructure.observability.metrics import AppMetrics
from geekvpn.infrastructure.observability.shared import SharedMetrics
from geekvpn.presentation.api.app import create_app
from tests.conftest import build_test_container

pytestmark = pytest.mark.integration

OTHER_WORKER = 'geekvpn_http_requests_total{method="GET",path="/api/miniapp/wallet",status="5xx"}'


def _settings(monkeypatch: pytest.MonkeyPatch, directory: Path | None) -> Settings:
    if directory is not None:
        monkeypatch.setenv("APP__METRICS_DIR", str(directory))
    get_settings.cache_clear()
    return get_settings()


def _another_worker(directory: Path) -> None:
    other = AppMetrics.create()
    other.http_requests.inc(7, method="GET", path="/api/miniapp/wallet", status="5xx")
    SharedMetrics(other.registry, directory=directory, worker_id="other").write()


def test_the_scrape_includes_the_other_workers_requests(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = _settings(monkeypatch, tmp_path)
    _another_worker(tmp_path)
    app = create_app(configured, container=build_test_container(configured))

    with TestClient(app) as client:
        body = client.get("/metrics").text

    assert f"{OTHER_WORKER} 7" in body


def test_the_running_worker_writes_its_own_file(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = _settings(monkeypatch, tmp_path)
    app = create_app(configured, container=build_test_container(configured))

    with TestClient(app):
        pass

    assert len(list(tmp_path.glob("*.json"))) == 1


def test_without_the_setting_the_scrape_is_this_process_alone(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _another_worker(tmp_path)
    configured = _settings(monkeypatch, None)
    assert configured.app.metrics_dir == ""
    app = create_app(configured, container=build_test_container(configured))

    with TestClient(app) as client:
        body = client.get("/metrics").text

    assert OTHER_WORKER not in body
