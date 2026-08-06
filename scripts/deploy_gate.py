"""Static consistency gate for the deployment configuration.

YAML that parses is not YAML that is correct. Every check here corresponds to a
failure that is invisible until production:

* a Prometheus scrape target that names a service which does not exist produces a
  permanently red target nobody notices on a dashboard they rarely open;
* an alert rule referencing a metric the application never registers is
  permanently silent, which is worse than having no alert, because it looks like
  coverage;
* an nginx ``proxy_pass`` to an undeclared upstream stops nginx from starting at
  all - discovered at deploy time, in front of customers;
* a compose file referencing an environment variable absent from ``.env.example``
  is a variable the next operator will not know to set.

Run with no arguments from the project root. Exits non-zero on any finding.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent

COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.monitoring.yml",
)

#: Standard exporter metrics. Referencing these is legitimate even though the
#: application does not register them.
EXTERNAL_METRIC_PREFIXES = ("node_", "pg_", "redis_", "up", "process_", "go_")

#: Written by scripts/backup.sh into node-exporter's textfile directory rather
#: than by the application, so it will never appear in metrics.py.
EXTERNAL_METRICS = {
    "geekvpn_backup_last_success_timestamp_seconds",
    "geekvpn_backup_size_bytes",
    "geekvpn_backup_count",
}

findings: list[str] = []


def fail(message: str) -> None:
    findings.append(message)


def load_yaml(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8")) or {}


def registered_metrics() -> set[str]:
    """Metric names the application actually registers.

    Read from the source with a regex rather than by importing the module,
    because this gate must run in CI before dependencies are installed.
    """
    source = (ROOT / "src/geekvpn/infrastructure/observability/metrics.py").read_text(encoding="utf-8")
    return set(re.findall(r'"(geekvpn_[a-z_]+)"', source))


def compose_services() -> set[str]:
    services: set[str] = set()
    for name in COMPOSE_FILES:
        services |= set((load_yaml(name).get("services") or {}).keys())
    return services


# ---------------------------------------------------------------------------
# 1. Every Prometheus scrape target must be a real service.
# ---------------------------------------------------------------------------
def check_scrape_targets(services: set[str]) -> None:
    prom = load_yaml("docker/monitoring/prometheus/prometheus.yml")
    checked = 0
    for job in prom.get("scrape_configs", []):
        for static in job.get("static_configs", []):
            for target in static.get("targets", []):
                host = target.split(":")[0]
                checked += 1
                if host in {"localhost", "127.0.0.1"}:
                    continue
                if host not in services:
                    fail(
                        f"prometheus job {job['job_name']!r} scrapes {target!r}, "
                        f"but no compose service is named {host!r}"
                    )
    print(f"  scrape targets checked: {checked}")


# ---------------------------------------------------------------------------
# 2. Every metric referenced by an alert rule must exist.
# ---------------------------------------------------------------------------
def check_alert_metrics(registered: set[str]) -> None:
    alerts = load_yaml("docker/monitoring/prometheus/alerts.yml")
    known = registered | EXTERNAL_METRICS
    rules = 0
    for group in alerts.get("groups", []):
        for rule in group.get("rules", []):
            rules += 1
            expr = rule["expr"]
            # Strip quoted label values before looking for metric names. Without
            # this, `status="5xx"` and `mountpoint="/host"` are read as metric
            # names, and the gate reports three findings that are not real. A
            # gate that cries wolf is a gate people stop running.
            expr_bare = re.sub(r'"[^"]*"', '""', expr)
            # Also strip the {{ $labels.x }} templating used in annotations that
            # some rules interpolate into the expression comment lines.
            expr_bare = re.sub(r"\{\{[^}]*\}\}", "", expr_bare)
            for raw in re.findall(r"\b([a-z][a-z0-9_]{3,})\b", expr_bare):
                if raw.endswith(("_bucket", "_sum", "_count")):
                    base = re.sub(r"_(bucket|sum|count)$", "", raw)
                else:
                    base = raw
                if base in known or raw in known:
                    continue
                if base.startswith(EXTERNAL_METRIC_PREFIXES) or raw.startswith(
                    EXTERNAL_METRIC_PREFIXES
                ):
                    continue
                # PromQL keywords and functions are not metrics.
                if base in _PROMQL_WORDS:
                    continue
                fail(
                    f"alert {rule['alert']!r} references {raw!r}, "
                    "which is neither a registered metric nor a known exporter metric"
                )
            for field in ("summary", "description", "runbook"):
                if not rule.get("annotations", {}).get(field):
                    fail(f"alert {rule['alert']!r} has no {field} annotation")
            if "for" not in rule:
                # An alert with no `for` fires on a single bad scrape, gets muted,
                # and then protects nothing.
                fail(f"alert {rule['alert']!r} has no 'for' duration")
            if rule.get("labels", {}).get("severity") not in {"warning", "critical"}:
                fail(f"alert {rule['alert']!r} has no usable severity label")
    print(f"  alert rules checked: {rules}")


_PROMQL_WORDS = {
    "sum", "rate", "avg", "max", "min", "count", "by", "without", "and", "or",
    "unless", "clamp_min", "clamp_max", "histogram_quantile", "predict_linear",
    "changes", "increase", "topk", "bottomk", "time", "job", "status", "le",
    "instance", "outcome", "mountpoint", "absent", "delta", "irate", "quantile",
    "environment", "colour", "policy", "kind", "panel", "channel", "result",
    "method", "path", "to_state", "version",
}


# ---------------------------------------------------------------------------
# 3. Every nginx proxy_pass upstream must be declared.
# ---------------------------------------------------------------------------
def check_nginx_upstreams() -> None:
    upstream_src = (ROOT / "docker/nginx/conf.d/00-upstreams.conf").read_text(encoding="utf-8")
    declared = set(re.findall(r"upstream\s+(\w+)\s*\{", upstream_src))

    active_src = (ROOT / "docker/nginx/conf.d/active-api.conf").read_text(encoding="utf-8")
    variables = set(re.findall(r"set\s+\$(\w+)\s+(\w+);", active_src))
    variable_names = {name for name, _ in variables}
    for _, value in variables:
        if value not in declared:
            fail(f"active-api.conf points at {value!r}, which is not a declared upstream")

    template = (ROOT / "docker/nginx/templates/geekvpn.conf").read_text(encoding="utf-8")
    passes = re.findall(r"proxy_pass\s+https?://([\w$]+)", template)
    for target in passes:
        if target.startswith("$"):
            if target[1:] not in variable_names:
                fail(f"proxy_pass uses ${target[1:]}, which no included file sets")
        elif target not in declared:
            fail(f"proxy_pass targets {target!r}, which is not a declared upstream")
    print(f"  upstreams declared: {len(declared)} | proxy_pass directives: {len(passes)}")

    # Every limit_req zone used must be defined in nginx.conf, or nginx refuses
    # to start with "unknown limit_req_zone".
    main = (ROOT / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    zones = set(re.findall(r"limit_req_zone\s+\S+\s+zone=(\w+):", main))
    for used in set(re.findall(r"limit_req\s+zone=(\w+)", template)):
        if used not in zones:
            fail(f"nginx uses limit_req zone {used!r}, which is not defined in nginx.conf")
    print(f"  limit_req zones defined: {sorted(zones)}")

    # Included snippet files must exist, or nginx fails to start.
    # Files the official nginx image already provides. They are not in our
    # repository and must not be, because shipping our own mime.types would
    # silently diverge from the base image on every upgrade.
    base_image_includes = {"/etc/nginx/mime.types", "/etc/nginx/fastcgi_params"}
    for include in set(re.findall(r"include\s+(/etc/nginx/[\w/.-]+);", template + main)):
        if "*" in include or include in base_image_includes:
            continue
        local = include.replace("/etc/nginx/", "docker/nginx/")
        if not (ROOT / local).exists():
            fail(f"nginx includes {include!r}, but {local} does not exist in the repository")


# ---------------------------------------------------------------------------
# 4. Environment variables referenced by compose must be documented.
# ---------------------------------------------------------------------------
def check_env_documented() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))
    referenced: set[str] = set()
    for name in COMPOSE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        referenced |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)[:?}-]", text))
    # Variables compose supplies itself or that are set inside containers.
    ignore = {"PWD", "HOME", "PATH"}
    missing = sorted(referenced - documented - ignore)
    for var in missing:
        fail(f"compose references ${{{var}}}, which is absent from .env.example")
    print(f"  env vars referenced by compose: {len(referenced)} | documented: {len(documented)}")


# ---------------------------------------------------------------------------
# 5. The Grafana dashboard must reference only real metrics.
# ---------------------------------------------------------------------------
def check_dashboard(registered: set[str]) -> None:
    path = ROOT / "docker/monitoring/grafana/dashboards/overview.json"
    blob = json.dumps(json.loads(path.read_text(encoding="utf-8")))
    used = set(re.findall(r"(geekvpn_[a-z_]+?)(?:_bucket|_sum|_count)?\b", blob))
    for metric in sorted(used - registered - EXTERNAL_METRICS):
        fail(f"the Grafana dashboard queries {metric!r}, which is not registered")
    print(f"  dashboard metrics referenced: {len(used)}")


# ---------------------------------------------------------------------------
# 6. Compose sanity: no production service may publish a database port.
# ---------------------------------------------------------------------------
def check_no_exposed_datastores() -> None:
    prod = load_yaml("docker-compose.prod.yml")
    monitoring = load_yaml("docker-compose.monitoring.yml")
    forbidden = {"postgres", "redis", "prometheus", "grafana", "alertmanager"}
    for source, data in (("prod", prod), ("monitoring", monitoring)):
        for service, config in (data.get("services") or {}).items():
            if service in forbidden and config.get("ports"):
                fail(
                    f"{source}: service {service!r} publishes ports {config['ports']!r}; "
                    "datastores and monitoring UIs must not be reachable from the internet"
                )
    print("  datastore port exposure: checked")


# ---------------------------------------------------------------------------
# 7. Every alert's runbook annotation must resolve to a real heading.
# ---------------------------------------------------------------------------
def check_runbook_anchors() -> None:
    doc_path = ROOT / "docs/runbook.md"
    if not doc_path.exists():
        fail("docs/runbook.md is missing, but every alert rule links to it")
        return
    doc = doc_path.read_text(encoding="utf-8")
    headings = {
        re.sub(r"[^a-z0-9]+", "-", heading.strip().lower()).strip("-")
        for heading in re.findall(r"^##\s+(.+)$", doc, re.MULTILINE)
    }
    alerts = load_yaml("docker/monitoring/prometheus/alerts.yml")
    checked = 0
    for group in alerts.get("groups") or []:
        for rule in group.get("rules") or []:
            annotation = (rule.get("annotations") or {}).get("runbook")
            if not annotation:
                continue  # presence is already enforced by check_alert_metrics
            checked += 1
            if "#" not in annotation:
                fail(f"alert {rule['alert']!r} has a runbook without an anchor")
                continue
            anchor = annotation.split("#", 1)[1]
            if anchor not in headings:
                fail(
                    f"alert {rule['alert']!r} links to docs/runbook.md#{anchor}, "
                    "which is not a heading in that file"
                )
    print(f"  runbook anchors checked: {checked} | sections available: {len(headings)}")


def main() -> int:
    print("deployment gate")
    registered = registered_metrics()
    services = compose_services()
    print(f"  registered metrics: {len(registered)} | compose services: {len(services)}")

    check_scrape_targets(services)
    check_alert_metrics(registered)
    check_nginx_upstreams()
    check_env_documented()
    check_dashboard(registered)
    check_no_exposed_datastores()
    check_runbook_anchors()

    if findings:
        print(f"\nDEPLOYMENT GATE: {len(findings)} finding(s)")
        for item in findings:
            print(f"  - {item}")
        return 1
    print("\nDEPLOYMENT GATE: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
