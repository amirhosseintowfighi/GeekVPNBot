"""Prometheus metrics, implemented against the exposition format directly.

Why not ``prometheus_client``
----------------------------
It is a fine library, and using it would be defensible. Two reasons not to here:

1. Its default registry exports a global mutable singleton and installs process
   collectors that read ``/proc``. Under Gunicorn with multiple workers that
   produces either wrong numbers or a multiprocess directory that has to be
   cleaned up on every restart, and the failure is silent — the numbers simply
   drift low.
2. The exposition format is about forty lines of text generation. Owning it means
   the label-cardinality guard below can refuse a bad metric at registration
   time rather than after it has already blown up Prometheus's memory.

The format implemented is the text format version 0.0.4, which is what every
Prome+theus scrape accepts.

The cardinality rule that matters
---------------------------------
The way self-hosted Prometheus dies is not CPU; it is a label with unbounded
values. One counter labelled with a raw request path produces a new time series
per user id in the URL, and a few days later the server is out of memory. So
``normalise_path`` collapses identifiers to placeholders, and
``FORBIDDEN_LABELS`` refuses the label names that are unbounded by nature. That
is a deliberate loss of detail: you cannot ask this system "how slow was this
specific user's request". That question belongs to logs, which are keyed by
correlation id and are cheap to store per-event.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

#: Content type Prometheus expects. Serving the wrong one makes a scrape fail
#: with a parse error rather than a connection error, which is harder to notice.
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: Latency buckets in seconds. Chosen around the thresholds we actually care
#: about rather than a generic decade spread: the p95 target is 500ms and the
#: p99 target is 1.5s, so there is resolution either side of both. Buckets are
#: cheap to add and impossible to change retroactively, so err toward more.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    1.5,
    3.0,
    5.0,
    10.0,
)

#: Label names that are unbounded by nature. Registering one of these is almost
#: always an accident, and the consequence lands on the monitoring server weeks
#: later, so it is refused at registration.
FORBIDDEN_LABELS = frozenset(
    {
        "user_id",
        "telegram_id",
        "payment_id",
        "order_id",
        "invoice_id",
        "ticket_id",
        "subscription_id",
        "correlation_id",
        "session_id",
        "token",
        "ip",
        "email",
        "card_number",
    }
)

_NAME_PATTERN = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DIGITS = re.compile(r"^\d+$")
_HEXISH = re.compile(r"^[0-9a-fA-F]{16,}$")


class MetricsError(ValueError):
    """Raised for a metric that would damage the monitoring system."""


def normalise_path(path: str) -> str:
    """Collapse identifiers in a URL path so the label stays bounded.

    ``/api/v1/payments/9f1c.../proof`` becomes ``/api/v1/payments/{id}/proof``.

    This is applied to the raw path rather than relying on the framework's route
    template because middleware runs before routing resolves, and a 404 has no
    route template at all — which is exactly the case a scanner hits thousands of
    times, and exactly the case that would otherwise create thousands of series.
    """
    if not path:
        return "/"
    path = _UUID.sub("{id}", path)
    segments = []
    for segment in path.split("/"):
        if _DIGITS.match(segment):
            segments.append("{n}")
        elif _HEXISH.match(segment):
            segments.append("{hash}")
        else:
            segments.append(segment)
    normalised = "/".join(segments)
    # Unknown paths all collapse together. A scanner probing /wp-admin, /.env and
    # ten thousand other paths must not be able to choose our label values.
    return normalised or "/"


def _validate_name(name: str) -> None:
    if not _NAME_PATTERN.match(name):
        raise MetricsError(f"Invalid metric name: {name!r}")


def _validate_labels(names: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    for name in names:
        if not _LABEL_PATTERN.match(name):
            raise MetricsError(f"Invalid label name: {name!r}")
        if name in FORBIDDEN_LABELS:
            raise MetricsError(
                f"Label {name!r} is unbounded and would create one time series per "
                "distinct value. Put it in a log line, not a metric."
            )
        if name in seen:
            raise MetricsError(f"Duplicate label name: {name!r}")
        seen.add(name)
    return tuple(names)


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_value(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if math.isnan(value):
        return "NaN"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


@dataclass(slots=True)
class _Metric:
    name: str
    documentation: str
    labelnames: tuple[str, ...]
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        # A metric with no help text is a number nobody can interpret. Prometheus
        # accepts it happily, which is exactly why this has to be refused here.
        if not self.documentation.strip():
            raise MetricsError(f"Metric {self.name!r} needs help text.")

    def _key(self, labels: Mapping[str, str] | None) -> tuple[str, ...]:
        labels = labels or {}
        if set(labels) != set(self.labelnames):
            raise MetricsError(
                f"{self.name} expects labels {sorted(self.labelnames)}, got {sorted(labels)}"
            )
        return tuple(str(labels[name]) for name in self.labelnames)

    def _label_suffix(self, key: Sequence[str], extra: Mapping[str, str] | None = None) -> str:
        pairs = [
            f'{name}="{_escape_label_value(value)}"'
            for name, value in zip(self.labelnames, key, strict=True)
        ]
        if extra:
            pairs.extend(f'{name}="{_escape_label_value(value)}"' for name, value in extra.items())
        return "{" + ",".join(pairs) + "}" if pairs else ""


class Counter(_Metric):
    """A value that only ever increases.

    Decrementing is refused rather than tolerated. A counter that can go down
    breaks ``rate()`` silently: Prometheus reads any decrease as a process
    restart and treats the drop as a gap, so the graph looks plausible and the
    numbers are wrong.
    """

    def __init__(self, name: str, documentation: str, labelnames: Sequence[str] = ()) -> None:
        _validate_name(name)
        super().__init__(name, documentation, _validate_labels(labelnames))
        self._values: dict[tuple[str, ...], float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise MetricsError("A counter cannot decrease.")
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.documentation}", f"# TYPE {self.name} counter"]
        if not self._values and not self.labelnames:
            lines.append(f"{self.name} 0")
        for key, value in sorted(self._values.items()):
            lines.append(f"{self.name}{self._label_suffix(key)} {_render_value(value)}")
        return lines


class Gauge(_Metric):
    """A value that can move in either direction."""

    def __init__(self, name: str, documentation: str, labelnames: Sequence[str] = ()) -> None:
        _validate_name(name)
        super().__init__(name, documentation, _validate_labels(labelnames))
        self._values: dict[tuple[str, ...], float] = {}

    def set(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.documentation}", f"# TYPE {self.name} gauge"]
        if not self._values and not self.labelnames:
            lines.append(f"{self.name} 0")
        for key, value in sorted(self._values.items()):
            lines.append(f"{self.name}{self._label_suffix(key)} {_render_value(value)}")
        return lines


class Histogram(_Metric):
    """Bucketed observations, for latency and payload sizes.

    Prometheus histogram buckets are cumulative: each bucket counts everything
    at or below its bound. Emitting non-cumulative counts is the classic
    implementation error and produces percentiles that are wrong in a way that
    still looks like a plausible graph.
    """

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ) -> None:
        _validate_name(name)
        bounds = tuple(sorted(float(b) for b in buckets))
        if not bounds:
            raise MetricsError("A histogram needs at least one bucket.")
        if len(set(bounds)) != len(bounds):
            raise MetricsError("Histogram buckets must be distinct.")
        super().__init__(name, documentation, _validate_labels(labelnames))
        self.buckets = bounds
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._totals: dict[tuple[str, ...], int] = {}

    def observe(self, value: float, **labels: str) -> None:
        if value < 0:
            # Every histogram here measures a duration or a size. A negative value
            # means the clock went backwards or the arithmetic is inverted; it
            # would silently corrupt _sum while the bucket counts still look sane.
            raise MetricsError(f"{self.name}: cannot observe a negative value ({value}).")
        key = self._key(labels)
        with self._lock:
            counts = self._counts.setdefault(key, [0] * len(self.buckets))
            for index, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[index] += 1
            self._sums[key] = self._sums.get(key, 0.0) + value
            self._totals[key] = self._totals.get(key, 0) + 1

    def count(self, **labels: str) -> int:
        return self._totals.get(self._key(labels), 0)

    def total(self, **labels: str) -> float:
        return self._sums.get(self._key(labels), 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.documentation}", f"# TYPE {self.name} histogram"]
        for key in sorted(self._counts):
            counts = self._counts[key]
            for bound, count in zip(self.buckets, counts, strict=True):
                suffix = self._label_suffix(key, {"le": _render_value(bound)})
                lines.append(f"{self.name}_bucket{suffix} {count}")
            total = self._totals[key]
            lines.append(f"{self.name}_bucket{self._label_suffix(key, {'le': '+Inf'})} {total}")
            lines.append(
                f"{self.name}_sum{self._label_suffix(key)} {_render_value(self._sums[key])}"
            )
            lines.append(f"{self.name}_count{self._label_suffix(key)} {total}")
        return lines


class MetricsRegistry:
    """An explicit registry, passed where it is needed.

    Not a module-level singleton: a global registry means tests share state, and
    the second test to register the same metric either raises or silently reuses
    the first one's data.
    """

    __slots__ = ("_metrics",)

    def __init__(self) -> None:
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}

    def register(self, metric: Counter | Gauge | Histogram) -> Counter | Gauge | Histogram:
        if metric.name in self._metrics:
            raise MetricsError(f"Metric {metric.name!r} is already registered.")
        self._metrics[metric.name] = metric
        return metric

    def counter(self, name: str, documentation: str, labelnames: Sequence[str] = ()) -> Counter:
        metric = Counter(name, documentation, labelnames)
        self.register(metric)
        return metric

    def gauge(self, name: str, documentation: str, labelnames: Sequence[str] = ()) -> Gauge:
        metric = Gauge(name, documentation, labelnames)
        self.register(metric)
        return metric

    def histogram(
        self,
        name: str,
        documentation: str,
        labelnames: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ) -> Histogram:
        metric = Histogram(name, documentation, labelnames, buckets)
        self.register(metric)
        return metric

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._metrics))

    def get(self, name: str) -> Counter | Gauge | Histogram | None:
        return self._metrics.get(name)

    def render(self) -> str:
        """Render the whole registry in the Prometheus text format."""
        blocks: list[str] = []
        for name in sorted(self._metrics):
            blocks.extend(self._metrics[name].render())
        # The format requires a trailing newline. Without it the last sample is
        # dropped by some parsers, which loses whichever metric sorts last and is
        # a genuinely baffling bug to chase.
        return "\n".join(blocks) + "\n"


@dataclass(slots=True, frozen=True)
class AppMetrics:
    """The metric set this application exports.

    Deliberately small. Every metric here answers a question someone actually
    asks during an incident; a metric nobody queries is a dashboard panel that
    gets ignored and a scrape cost that does not.
    """

    registry: MetricsRegistry
    http_requests: Counter
    http_duration: Histogram
    http_in_flight: Gauge
    rate_limited: Counter
    auth_failures: Counter
    payments_awaiting_review: Gauge
    payment_transitions: Counter
    provisioning_failures: Counter
    panel_latency: Histogram
    notifications_sent: Counter
    cache_operations: Counter
    build_info: Gauge

    @classmethod
    def create(cls, registry: MetricsRegistry | None = None) -> AppMetrics:
        registry = registry or MetricsRegistry()
        return cls(
            registry=registry,
            http_requests=registry.counter(
                "geekvpn_http_requests_total",
                "HTTP requests by normalised path, method and status class.",
                ("method", "path", "status"),
            ),
            http_duration=registry.histogram(
                "geekvpn_http_request_duration_seconds",
                "HTTP request latency in seconds.",
                ("method", "path"),
            ),
            http_in_flight=registry.gauge(
                "geekvpn_http_requests_in_flight",
                "Requests currently being served.",
            ),
            rate_limited=registry.counter(
                "geekvpn_rate_limited_total",
                "Requests refused by the rate limiter, by policy.",
                ("policy",),
            ),
            auth_failures=registry.counter(
                "geekvpn_auth_failures_total",
                "Failed authentication attempts by kind.",
                ("kind",),
            ),
            payments_awaiting_review=registry.gauge(
                "geekvpn_payments_awaiting_review",
                "Card and crypto payments waiting for an operator decision.",
            ),
            payment_transitions=registry.counter(
                "geekvpn_payment_transitions_total",
                "Payment state transitions.",
                ("method", "to_state"),
            ),
            provisioning_failures=registry.counter(
                "geekvpn_provisioning_failures_total",
                "Provisioning attempts that failed, by panel kind.",
                ("panel",),
            ),
            panel_latency=registry.histogram(
                "geekvpn_panel_request_duration_seconds",
                "Latency of calls to an upstream VPN panel.",
                ("panel", "operation"),
            ),
            notifications_sent=registry.counter(
                "geekvpn_notifications_total",
                "Notification deliveries by channel and outcome.",
                ("channel", "outcome"),
            ),
            cache_operations=registry.counter(
                "geekvpn_cache_operations_total",
                "Cache operations by result.",
                ("result",),
            ),
            build_info=registry.gauge(
                "geekvpn_build_info",
                "Always 1, labelled with the running version. Lets a dashboard show "
                "which build served a request and makes a failed deploy visible.",
                ("version", "environment"),
            ),
        )


def status_class(status_code: int) -> str:
    """Bucket a status code as ``2xx``, ``4xx`` and so on.

    The exact code is in the logs. As a label, the class is what alerts are
    written against, and it keeps the series count at five instead of sixty.
    """
    return f"{status_code // 100}xx"


__all__ = [
    "CONTENT_TYPE",
    "DEFAULT_BUCKETS",
    "FORBIDDEN_LABELS",
    "AppMetrics",
    "Counter",
    "Gauge",
    "Histogram",
    "MetricsError",
    "MetricsRegistry",
    "normalise_path",
    "status_class",
]
