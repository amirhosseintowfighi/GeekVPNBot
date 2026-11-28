"""One container, several uvicorn workers, one set of numbers.

Production runs ``uvicorn --workers=4`` and each worker is a separate process
with its own registry. A scrape is answered by whichever worker is free, so
before this Prometheus saw four unrelated counters taking turns - 996, 1147,
1147, 996 - and read every drop as a restart. ``rate()`` then measured each
worker's lifetime totals instead of the last five minutes, and a burst of 5xx
from days ago kept `HighErrorRate` firing with no error in the logs.

Each worker now writes its numbers to a shared directory and the scrape adds
them up. These pin what that has to get right: any worker answers with the
same total, a counter never goes down between scrapes, a dead worker's
requests still count but its in-flight gauge does not, and `build_info` stays 1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geekvpn.infrastructure.observability.metrics import AppMetrics
from geekvpn.infrastructure.observability.shared import SharedMetrics

pytestmark = pytest.mark.unit

REQUESTS = "geekvpn_http_requests_total"
OK = {"method": "GET", "path": "/api/miniapp/wallet", "status": "2xx"}
FAILED = {"method": "GET", "path": "/api/miniapp/wallet", "status": "5xx"}


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class Worker:
    """One uvicorn worker: its own registry, writing to the shared directory."""

    def __init__(self, directory: Path, clock: Clock, name: str) -> None:
        self.metrics = AppMetrics.create()
        self.metrics.build_info.set(1, version="1.0.0", environment="production")
        self.shared = SharedMetrics(
            self.metrics.registry, directory=directory, clock=clock, worker_id=name
        )

    def serve(self, count: int, labels: dict[str, str] = OK) -> None:
        self.metrics.http_requests.inc(count, **labels)

    def scrape(self) -> dict[str, float]:
        return _samples(self.shared.render())


def _samples(text: str) -> dict[str, float]:
    samples: dict[str, float] = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.rpartition(" ")
            samples[name] = float(value)
    return samples


def _requests(samples: dict[str, float], labels: dict[str, str]) -> float:
    key = REQUESTS + "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    return samples.get(key, 0.0)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def workers(tmp_path: Path, clock: Clock) -> list[Worker]:
    return [Worker(tmp_path, clock, f"w{index}") for index in range(4)]


def test_any_worker_answers_with_the_whole_containers_count(workers: list[Worker]) -> None:
    for index, worker in enumerate(workers):
        worker.serve(10 * (index + 1))
        worker.shared.write()

    totals = {_requests(worker.scrape(), OK) for worker in workers}

    assert totals == {10 + 20 + 30 + 40}


def test_a_counter_never_goes_down_whichever_worker_is_scraped(
    workers: list[Worker], clock: Clock
) -> None:
    """The bug itself: alternating workers used to read as a reset every scrape."""
    seen: list[float] = []
    for scrape in range(12):
        for index, worker in enumerate(workers):
            worker.serve(index + 1, FAILED if scrape % 3 == 0 else OK)
        # Every worker writes on its own timer; the scrape lands on any one.
        for worker in workers:
            worker.shared.write()
        clock.now += 15
        seen.append(_requests(workers[scrape % len(workers)].scrape(), OK))

    assert seen == sorted(seen)


def test_the_answering_worker_reports_its_own_latest_count(
    workers: list[Worker],
) -> None:
    """Its own numbers come from memory, not from a file a few seconds old."""
    first, second = workers[0], workers[1]
    first.serve(5)
    first.shared.write()
    first.serve(3)

    assert _requests(first.scrape(), OK) == 8
    assert _requests(second.scrape(), OK) == 5


def test_a_worker_that_died_still_counts_for_the_requests_it_served(
    tmp_path: Path, clock: Clock
) -> None:
    """Dropping it would lower the total, and a lower total reads as a reset."""
    dead = Worker(tmp_path, clock, "dead")
    dead.serve(100)
    dead.shared.write()
    clock.now += 3_600

    survivor = Worker(tmp_path, clock, "alive")
    survivor.serve(1)

    assert _requests(survivor.scrape(), OK) == 101


def test_requests_in_flight_add_up_from_live_workers_only(tmp_path: Path, clock: Clock) -> None:
    dead = Worker(tmp_path, clock, "dead")
    dead.metrics.http_in_flight.inc(7)
    dead.shared.write()
    clock.now += 3_600

    busy = Worker(tmp_path, clock, "busy")
    busy.metrics.http_in_flight.inc(2)
    busy.shared.write()
    answering = Worker(tmp_path, clock, "answering")
    answering.metrics.http_in_flight.inc(1)

    assert answering.scrape()["geekvpn_http_requests_in_flight"] == 3


def test_build_info_stays_one_however_many_workers(workers: list[Worker]) -> None:
    for worker in workers:
        worker.shared.write()

    samples = workers[0].scrape()

    assert samples['geekvpn_build_info{version="1.0.0",environment="production"}'] == 1


def test_latency_histograms_add_up_bucket_by_bucket(workers: list[Worker]) -> None:
    labels = {"method": "GET", "path": "/api/miniapp/wallet"}
    workers[0].metrics.http_duration.observe(0.02, **labels)
    workers[1].metrics.http_duration.observe(0.4, **labels)
    workers[1].shared.write()

    samples = workers[0].scrape()

    prefix = 'geekvpn_http_request_duration_seconds_bucket{method="GET",path="/api/miniapp/wallet"'
    assert samples[prefix + ',le="0.025"}'] == 1
    assert samples[prefix + ',le="0.5"}'] == 2
    assert samples[prefix + ',le="+Inf"}'] == 2
    count = 'geekvpn_http_request_duration_seconds_count{method="GET",path="/api/miniapp/wallet"}'
    assert samples[count] == 2


def test_a_file_that_cannot_be_read_is_skipped_not_fatal(
    tmp_path: Path, workers: list[Worker]
) -> None:
    """A scrape that raises is a gap in every graph at once."""
    workers[1].serve(4)
    workers[1].shared.write()
    (tmp_path / "torn.json").write_text("{not json")
    (tmp_path / "wrong.json").write_text(json.dumps({"metrics": {REQUESTS: "nonsense"}}))

    assert _requests(workers[0].scrape(), OK) == 4


def test_writing_replaces_the_file_rather_than_appending(
    tmp_path: Path, workers: list[Worker]
) -> None:
    worker = workers[0]
    worker.serve(1)
    worker.shared.write()
    worker.serve(1)
    worker.shared.write()

    assert len(list(tmp_path.glob("*.json"))) == 1
    assert _requests(workers[1].scrape(), OK) == 2
