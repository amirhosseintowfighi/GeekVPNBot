"""Tests for the metrics registry.

The interesting cases here are the refusals, not the happy paths. A metrics layer
that accepts a user id as a label does not fail loudly - it quietly produces
unbounded cardinality that takes Prometheus down days later, and it leaks personal
data into a system with a much weaker access model than the database.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.observability.metrics import (
    AppMetrics,
    Counter,
    Gauge,
    Histogram,
    MetricsError,
    MetricsRegistry,
    normalise_path,
    status_class,
)


class TestNameValidation:
    def test_a_valid_name_is_accepted(self) -> None:
        registry = MetricsRegistry()
        registry.counter("geekvpn_things_total", "Things.")
        assert "geekvpn_things_total" in registry.names()

    @pytest.mark.parametrize(
        "name",
        [
            "1_starts_with_a_digit",
            "has-a-hyphen",
            "has a space",
            "has.a.dot",
            "",
        ],
    )
    def test_an_invalid_name_is_refused(self, name: str) -> None:
        registry = MetricsRegistry()
        with pytest.raises(MetricsError):
            registry.counter(name, "Help.")

    def test_registering_the_same_name_twice_is_refused(self) -> None:
        # Two metrics with one name produce a scrape Prometheus rejects wholesale,
        # so every other metric disappears too.
        registry = MetricsRegistry()
        registry.counter("geekvpn_dupe_total", "First.")
        with pytest.raises(MetricsError):
            registry.counter("geekvpn_dupe_total", "Second.")

    def test_help_text_is_required(self) -> None:
        registry = MetricsRegistry()
        with pytest.raises(MetricsError):
            registry.counter("geekvpn_nohelp_total", "")


class TestForbiddenLabels:
    @pytest.mark.parametrize(
        "label",
        ["user_id", "telegram_id", "payment_id", "correlation_id", "ip", "card_number"],
    )
    def test_an_identifying_label_is_refused_at_registration(self, label: str) -> None:
        # Refused at registration, not at observation: the mistake must be
        # impossible to deploy, not merely detectable in production.
        registry = MetricsRegistry()
        with pytest.raises(MetricsError):
            registry.counter("geekvpn_leaky_total", "Leaks.", labelnames=(label,))

    def test_a_bounded_label_is_accepted(self) -> None:
        registry = MetricsRegistry()
        metric = registry.counter("geekvpn_ok_total", "Fine.", labelnames=("method", "status"))
        metric.inc(method="GET", status="2xx")
        assert "geekvpn_ok_total" in registry.render()


class TestCounter:
    def test_it_starts_at_zero_and_increments(self) -> None:
        counter = Counter("geekvpn_c_total", "C.")
        assert counter.value() == 0
        counter.inc()
        counter.inc(2)
        assert counter.value() == 3

    def test_it_refuses_to_decrease(self) -> None:
        # A counter that can go down breaks rate() silently: Prometheus reads the
        # decrease as a counter reset and invents a spike.
        counter = Counter("geekvpn_c_total", "C.")
        with pytest.raises(MetricsError):
            counter.inc(-1)

    def test_labels_are_tracked_independently(self) -> None:
        counter = Counter("geekvpn_c_total", "C.", labelnames=("kind",))
        counter.inc(kind="a")
        counter.inc(2, kind="b")
        assert counter.value(kind="a") == 1
        assert counter.value(kind="b") == 2

    def test_a_missing_label_is_refused(self) -> None:
        counter = Counter("geekvpn_c_total", "C.", labelnames=("kind",))
        with pytest.raises(MetricsError):
            counter.inc()

    def test_an_unexpected_label_is_refused(self) -> None:
        counter = Counter("geekvpn_c_total", "C.", labelnames=("kind",))
        with pytest.raises(MetricsError):
            counter.inc(kind="a", extra="b")


class TestGauge:
    def test_it_can_move_in_both_directions(self) -> None:
        gauge = Gauge("geekvpn_g", "G.")
        gauge.set(5)
        gauge.dec()
        gauge.inc(2)
        assert gauge.value() == 6

    def test_it_may_go_negative(self) -> None:
        # Unlike a counter. A gauge legitimately represents a signed quantity.
        gauge = Gauge("geekvpn_g", "G.")
        gauge.dec(3)
        assert gauge.value() == -3


class TestHistogram:
    def test_buckets_are_cumulative(self) -> None:
        histogram = Histogram("geekvpn_h_seconds", "H.", buckets=(0.1, 1.0))
        histogram.observe(0.05)
        histogram.observe(0.5)
        histogram.observe(5.0)
        rendered = "\n".join(histogram.render())
        # A value in the 0.1 bucket must also appear in the 1.0 bucket, or
        # histogram_quantile produces nonsense.
        assert 'le="0.1"} 1' in rendered
        assert 'le="1"} 2' in rendered or 'le="1.0"} 2' in rendered
        assert 'le="+Inf"} 3' in rendered

    def test_sum_and_count_are_exposed(self) -> None:
        histogram = Histogram("geekvpn_h_seconds", "H.", buckets=(1.0,))
        histogram.observe(0.25)
        histogram.observe(0.75)
        rendered = "\n".join(histogram.render())
        assert "geekvpn_h_seconds_count" in rendered
        assert "geekvpn_h_seconds_sum" in rendered

    def test_unsorted_buckets_are_normalised_rather_than_refused(self) -> None:
        # The constructor sorts. That is the better behaviour: the caller's intent
        # is unambiguous, and cumulative counts against unsorted bounds would be
        # silently wrong. Asserted so the choice is deliberate rather than assumed.
        histogram = Histogram("geekvpn_h_seconds", "H.", buckets=(1.0, 0.1))
        assert histogram.buckets == (0.1, 1.0)

    def test_duplicate_buckets_are_refused(self) -> None:
        with pytest.raises(MetricsError):
            Histogram("geekvpn_h_seconds", "H.", buckets=(0.1, 0.1))

    def test_an_empty_bucket_list_is_refused(self) -> None:
        with pytest.raises(MetricsError):
            Histogram("geekvpn_h_seconds", "H.", buckets=())

    def test_a_negative_observation_is_refused(self) -> None:
        histogram = Histogram("geekvpn_h_seconds", "H.", buckets=(1.0,))
        with pytest.raises(MetricsError):
            histogram.observe(-0.1)


class TestNormalisePath:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/api/v1/users/3f0c9a2e-0000-4000-8000-000000000001", "/api/v1/users/{id}"),
            ("/api/v1/payments/12345", "/api/v1/payments/{n}"),
            ("/api/v1/catalog", "/api/v1/catalog"),
            ("/health/ready", "/health/ready"),
        ],
    )
    def test_identifiers_are_collapsed(self, raw: str, expected: str) -> None:
        # Without this, one series per customer per endpoint. Cardinality is the
        # way self-hosted Prometheus actually dies.
        assert normalise_path(raw) == expected

    def test_a_long_hex_segment_is_collapsed(self) -> None:
        assert normalise_path("/api/v1/x/2bf3eeba68c822fd14392b430fc1aed9") == "/api/v1/x/{hash}"


class TestStatusClass:
    @pytest.mark.parametrize(
        "code,expected",
        [(200, "2xx"), (204, "2xx"), (301, "3xx"), (404, "4xx"), (429, "4xx"), (503, "5xx")],
    )
    def test_codes_are_bucketed(self, code: int, expected: str) -> None:
        assert status_class(code) == expected


class TestExposition:
    def test_the_render_has_help_and_type_lines(self) -> None:
        registry = MetricsRegistry()
        registry.counter("geekvpn_e_total", "Explained.")
        rendered = registry.render()
        assert "# HELP geekvpn_e_total Explained." in rendered
        assert "# TYPE geekvpn_e_total counter" in rendered

    def test_label_values_are_escaped(self) -> None:
        # A quote or newline in a label value corrupts the whole scrape, and label
        # values are not always as trusted as they look.
        registry = MetricsRegistry()
        metric = registry.counter("geekvpn_e_total", "E.", labelnames=("kind",))
        metric.inc(kind='we"ird\nvalue')
        rendered = registry.render()
        assert '\\"' in rendered
        assert "\\n" in rendered
        # No raw newline inside the label braces.
        for line in rendered.splitlines():
            assert not line.startswith('value"}')

    def test_an_empty_registry_renders_without_error(self) -> None:
        assert MetricsRegistry().render() == "" or MetricsRegistry().render().endswith("\n")


class TestAppMetrics:
    def test_it_registers_the_expected_metrics(self) -> None:
        metrics = AppMetrics.create()
        names = set(metrics.registry.names())
        # The alert rules, the Grafana dashboard and deploy_gate.py all depend on
        # these exact names. Renaming one silently disables an alert.
        expected = {
            "geekvpn_http_requests_total",
            "geekvpn_http_request_duration_seconds",
            "geekvpn_http_requests_in_flight",
            "geekvpn_rate_limited_total",
            "geekvpn_auth_failures_total",
            "geekvpn_payments_awaiting_review",
            "geekvpn_payment_transitions_total",
            "geekvpn_provisioning_failures_total",
            "geekvpn_panel_request_duration_seconds",
            "geekvpn_notifications_total",
            "geekvpn_cache_operations_total",
            "geekvpn_build_info",
        }
        assert expected <= names, sorted(expected - names)

    def test_build_info_carries_version_and_environment(self) -> None:
        metrics = AppMetrics.create()
        metrics.build_info.set(1, version="1.2.3", environment="production")
        rendered = metrics.registry.render()
        assert 'version="1.2.3"' in rendered
        assert 'environment="production"' in rendered

    def test_a_full_request_can_be_recorded(self) -> None:
        metrics = AppMetrics.create()
        metrics.http_in_flight.inc()
        metrics.http_requests.inc(method="GET", path="/api/v1/catalog", status="2xx")
        metrics.http_duration.observe(0.042, method="GET", path="/api/v1/catalog")
        metrics.http_in_flight.dec()
        rendered = metrics.registry.render()
        assert "geekvpn_http_requests_total" in rendered
        assert metrics.http_in_flight.value() == 0

    def test_two_instances_do_not_share_state(self) -> None:
        # Module-level default registries are how one test's counters leak into
        # another's assertions.
        first = AppMetrics.create()
        second = AppMetrics.create()
        first.http_in_flight.inc()
        assert second.http_in_flight.value() == 0
