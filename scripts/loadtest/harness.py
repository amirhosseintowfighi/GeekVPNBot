"""Load-test harness built on the standard library only.

Why not locust or k6 as the primary tool: adding a dependency that only runs on
a developer's laptop means the test is never run. This uses ``asyncio`` and
``urllib`` from the standard library, so it runs anywhere Python does, including
inside the deployment image. ``k6.js`` next to this file is the option for a real
load rig, where distributed generation and proper percentile aggregation matter.

What this measures honestly
---------------------------
It measures **the API under concurrent load from one machine**. It does not
measure what a real load test measures: a single client process is itself a
bottleneck well before a properly sized server is, and latency figures from one
box include that box's scheduling noise. Treat the numbers as a regression signal
between runs on the same machine, not as a capacity figure to quote.

What it is genuinely good at is the two questions that matter for Phase 13:

1. **Does the rate limiter actually refuse?** Fire more requests than the policy
   permits and count the 429s. A limiter that is wired but not working looks
   identical to a working one until you do this.
2. **Does the limiter fail open when Redis is unreachable?** Stop Redis and
   confirm requests still succeed. The code claims this posture in three
   docstrings; this is the only thing that proves it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass(slots=True)
class Result:
    status: int
    elapsed_ms: float
    error: str = ""


@dataclass(slots=True)
class Report:
    label: str
    results: list[Result] = field(default_factory=list)
    wall_seconds: float = 0.0

    @property
    def total(self) -> int:
        return len(self.results)

    def count(self, status: int) -> int:
        return sum(1 for item in self.results if item.status == status)

    @property
    def successes(self) -> int:
        return sum(1 for item in self.results if 200 <= item.status < 300)

    @property
    def throttled(self) -> int:
        return self.count(429)

    @property
    def errors(self) -> int:
        return sum(1 for item in self.results if item.status == 0 or item.status >= 500)

    def percentile(self, fraction: float) -> float:
        """Nearest-rank percentile over successful requests.

        Failures are excluded deliberately: a connection refused in two
        milliseconds would otherwise improve the p50 and make an outage look like
        a performance win.
        """
        samples = sorted(item.elapsed_ms for item in self.results if 200 <= item.status < 300)
        if not samples:
            return 0.0
        index = max(0, min(len(samples) - 1, int(round(fraction * (len(samples) - 1)))))
        return samples[index]

    def summary(self) -> str:
        rate = self.total / self.wall_seconds if self.wall_seconds else 0.0
        median = statistics.median(
            [item.elapsed_ms for item in self.results if 200 <= item.status < 300] or [0.0]
        )
        return (
            f"{self.label}\n"
            f"  requests      : {self.total} in {self.wall_seconds:.2f}s ({rate:.1f}/s)\n"
            f"  2xx           : {self.successes}\n"
            f"  429 throttled : {self.throttled}\n"
            f"  5xx / failed  : {self.errors}\n"
            f"  latency p50   : {median:.1f} ms\n"
            f"  latency p95   : {self.percentile(0.95):.1f} ms\n"
            f"  latency p99   : {self.percentile(0.99):.1f} ms"
        )


def _fetch(url: str, *, method: str, headers: dict[str, str], body: bytes | None) -> Result:
    request = urllib.request.Request(url, method=method, data=body, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        # A 429 is the expected outcome of this test, not an error.
        status = exc.code
        exc.read()
    except Exception as exc:  # connection refused, timeout, DNS
        return Result(0, (time.perf_counter() - started) * 1000, str(exc))
    return Result(status, (time.perf_counter() - started) * 1000)


async def run(
    url: str,
    *,
    label: str,
    total: int,
    concurrency: int,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict | None = None,
) -> Report:
    """Fire ``total`` requests with at most ``concurrency`` in flight.

    A semaphore rather than batching: batches of N wait for the slowest request
    in each batch, which quietly reduces the real concurrency and makes the
    server look better than it is.
    """
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"

    semaphore = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()
    report = Report(label=label)

    async def one() -> Result:
        async with semaphore:
            # urllib is blocking, so it runs in the default executor. This is the
            # harness's own ceiling and the reason the numbers are a regression
            # signal rather than a capacity measurement.
            return await loop.run_in_executor(
                None, _fetch, url, method=method, headers=request_headers, body=payload
            )

    started = time.perf_counter()
    report.results = list(await asyncio.gather(*(one() for _ in range(total))))
    report.wall_seconds = time.perf_counter() - started
    return report


async def scenario_health(base: str, concurrency: int) -> Report:
    """Baseline. Exempt from rate limiting, so this is pure request overhead."""
    return await run(
        f"{base}/health/live", label="health (baseline)", total=concurrency * 20, concurrency=concurrency
    )


async def scenario_catalog(base: str, concurrency: int) -> Report:
    """A real read path: database and cache, limited by ``catalog.browse``."""
    return await run(
        f"{base}/api/v1/catalog/products",
        label="catalog browse",
        total=concurrency * 20,
        concurrency=concurrency,
    )


async def scenario_rate_limit(base: str) -> Report:
    """Deliberately exceed ``auth.login`` and expect refusals.

    A run that reports zero 429s here is a **failed** run: it means the limiter is
    not doing anything, which is exactly the silent failure this scenario exists
    to catch.
    """
    return await run(
        f"{base}/api/v1/auth/telegram",
        label="rate limit probe (429s are the pass condition)",
        total=120,
        concurrency=20,
        method="POST",
        body={"init_data": "deliberately-invalid"},
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Geek VPN load harness")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument(
        "--scenario",
        choices=("all", "health", "catalog", "ratelimit"),
        default="all",
    )
    args = parser.parse_args()

    reports: list[Report] = []
    if args.scenario in ("all", "health"):
        reports.append(await scenario_health(args.base, args.concurrency))
    if args.scenario in ("all", "catalog"):
        reports.append(await scenario_catalog(args.base, args.concurrency))
    if args.scenario in ("all", "ratelimit"):
        reports.append(await scenario_rate_limit(args.base))

    print()
    for report in reports:
        print(report.summary())
        print()

    limit_report = next((r for r in reports if "rate limit" in r.label), None)
    if limit_report is not None and limit_report.throttled == 0:
        print("FAIL: the rate limit probe was never refused. The limiter is not working.")
        return 1
    if any(report.errors for report in reports):
        print("FAIL: at least one request failed or returned 5xx.")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
