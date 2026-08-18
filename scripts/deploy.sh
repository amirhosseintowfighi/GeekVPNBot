#!/usr/bin/env bash
# Blue/green deployment with no downtime.
#
# How it works: two identical API services exist (api_blue, api_green). Exactly
# one receives traffic, decided by a single `set $active_api ...;` line that nginx
# includes. A deploy starts the idle colour, waits until it reports READY, flips
# that one line, reloads nginx, then drains and stops the old colour.
#
# Why this design rather than `docker compose up --wait api`:
#   * recreating a service in place means a window with no healthy container;
#   * `nginx -s reload` keeps existing connections alive on the old workers until
#     they finish, so in-flight requests are not cut off;
#   * rollback is the same flip in reverse and takes about a second, which means
#     rolling back is never a decision anyone has to be brave about.
#
# Migrations run BEFORE the new colour starts, and this is the sharp edge of the
# whole approach: for a moment both the old and new code run against the new
# schema. Every migration must therefore be backwards compatible with the
# currently deployed code - add columns, never rename or drop in the same release.
# Drops belong in a follow-up release after the old code is gone. This constraint
# is documented in docs/deployment.md because violating it is invisible in
# staging, where only one version is ever running.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR"

ACTIVE_FILE="docker/nginx/conf.d/active-api.conf"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"
[[ -f docker-compose.monitoring.yml && "${WITH_MONITORING:-1}" == "1" ]] && \
  COMPOSE_FILES="${COMPOSE_FILES} -f docker-compose.monitoring.yml"
COMPOSE="docker compose ${COMPOSE_FILES}"

READY_TIMEOUT="${READY_TIMEOUT:-120}"
DRAIN_SECONDS="${DRAIN_SECONDS:-15}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-30}"

log()  { printf '\033[0;36m[deploy]\033[0m %s %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
warn() { printf '\033[0;33m[deploy]\033[0m %s WARNING: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die()  { printf '\033[0;31m[deploy]\033[0m %s FAILED: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; exit 1; }

current_colour() {
  # Parsed from the file nginx actually reads, not from a separate state file.
  # Two sources of truth for "which colour is live" is how a deploy ends up
  # switching to the colour that is already serving.
  grep -oE 'api_(blue|green)' "$ACTIVE_FILE" | head -1
}

idle_colour() {
  [[ "$(current_colour)" == "api_blue" ]] && echo "api_green" || echo "api_blue"
}

wait_ready() {
  local service="$1" deadline=$(( $(date +%s) + READY_TIMEOUT ))
  log "waiting for ${service} to report ready (timeout ${READY_TIMEOUT}s)"
  while (( $(date +%s) < deadline )); do
    local state
    state=$($COMPOSE ps --format '{{.Health}}' "$service" 2>/dev/null | head -1 || true)
    case "$state" in
      healthy)   log "${service} is healthy"; return 0 ;;
      unhealthy) die "${service} reported unhealthy; not switching traffic" ;;
    esac
    # Container-level health uses /health/ready, which checks Postgres and Redis.
    # A container that is merely running is not a container that can serve.
    sleep 3
  done
  die "${service} did not become healthy within ${READY_TIMEOUT}s"
}

smoke_test() {
  local service="$1"
  log "smoke testing ${service} directly, before it receives any traffic"
  # Executed inside the container against localhost, so it tests the new code
  # without going through nginx - which is still pointed at the old colour.
  $COMPOSE exec -T "$service" python -m geekvpn.entrypoints.healthcheck \
      http://localhost:8000/health/ready \
    || die "${service} failed its readiness smoke test"
  # The metrics endpoint is a second, independent signal: it proves the app
  # assembled its middleware stack, not merely that a socket is open.
  $COMPOSE exec -T "$service" python -c "
import sys, urllib.request
try:
    body = urllib.request.urlopen('http://localhost:8000/metrics', timeout=5).read().decode()
except Exception as exc:
    print(f'metrics endpoint unreachable: {exc}'); sys.exit(1)
if 'geekvpn_build_info' not in body:
    print('metrics endpoint did not expose build info'); sys.exit(1)
print('metrics ok')
" || die "${service} did not expose usable metrics"
}

switch_to() {
  local colour="$1"
  log "switching nginx to ${colour}"
  printf '%s\n' \
    '# Which colour currently serves traffic. Rewritten by scripts/deploy.sh.' \
    "set \$active_api ${colour};" > "$ACTIVE_FILE"
  # Validate before reloading. `nginx -s reload` on a broken config leaves the
  # old workers running and prints an error nobody reads, so the deploy would
  # look successful while serving the previous version forever.
  $COMPOSE exec -T nginx nginx -t || die "nginx rejected the new config; traffic unchanged"
  $COMPOSE exec -T nginx nginx -s reload || die "nginx reload failed"
  log "traffic now flows to ${colour}"
}

verify_through_edge() {
  log "verifying through nginx"
  local deadline=$(( $(date +%s) + SMOKE_TIMEOUT ))
  while (( $(date +%s) < deadline )); do
    if $COMPOSE exec -T nginx wget -qO- --timeout=5 http://localhost/health/ready >/dev/null 2>&1; then
      log "the edge is serving the new colour"
      return 0
    fi
    sleep 2
  done
  return 1
}

# ---------------------------------------------------------------------------
case "${1:-deploy}" in
  status)
    echo "active colour : $(current_colour)"
    echo "idle colour   : $(idle_colour)"
    $COMPOSE ps
    exit 0
    ;;

  rollback)
    PREVIOUS=$(idle_colour)
    log "rolling back to ${PREVIOUS}"
    # The old colour is only stopped at the end of a deploy, and only after the
    # new one has served real traffic. If it is still running, rollback is one
    # config flip. If it is not, it has to be started first - slower, but still
    # the previous image.
    if [[ "$($COMPOSE ps --format '{{.State}}' "$PREVIOUS" 2>/dev/null | head -1)" != "running" ]]; then
      warn "${PREVIOUS} is not running; starting it"
      $COMPOSE up -d --no-deps "$PREVIOUS"
      wait_ready "$PREVIOUS"
    fi
    switch_to "$PREVIOUS"
    verify_through_edge || die "rollback did not verify through nginx; investigate immediately"
    log "rolled back. NOTE: the database schema was NOT rolled back."
    log "If this release included a migration, confirm the previous code tolerates it."
    exit 0
    ;;

  deploy) ;;
  *) die "unknown command: $1 (expected deploy, rollback or status)" ;;
esac

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
[[ -f .env ]] || die ".env is missing; refusing to deploy with defaults"

ACTIVE=$(current_colour)
IDLE=$(idle_colour)
[[ -n "$ACTIVE" ]] || die "could not determine the active colour from ${ACTIVE_FILE}"
log "active: ${ACTIVE}  ->  deploying to: ${IDLE}"

log "building images"
$COMPOSE build --pull "$IDLE" nginx || die "build failed"

log "ensuring infrastructure is up"
$COMPOSE up -d postgres redis || die "could not start postgres/redis"

log "running migrations"
# Before the new colour starts, and while the old one is still serving. See the
# header: every migration must be readable by the currently deployed code.
$COMPOSE run --rm migrate || die "migrations failed; nothing was deployed"

log "starting ${IDLE}"
$COMPOSE up -d --no-deps "$IDLE" || die "could not start ${IDLE}"

# Idempotent, and required on a first install: switch_to reloads nginx with
# `compose exec`, which fails outright if the container has never been
# started. On an upgrade this is a no-op because nginx is already up.
log "ensuring the edge is up"
$COMPOSE up -d nginx || die "could not start nginx"
wait_ready "$IDLE"
smoke_test "$IDLE"

switch_to "$IDLE"

if ! verify_through_edge; then
  warn "the edge did not verify; rolling back to ${ACTIVE}"
  switch_to "$ACTIVE"
  die "deploy rolled back automatically. ${IDLE} is still running for inspection."
fi

log "draining ${ACTIVE} for ${DRAIN_SECONDS}s"
# Nginx has stopped sending new requests to the old colour, but requests already
# in flight are still finishing. Stopping immediately would cut off exactly the
# slowest requests - which, given the analytics exports, are the ones an operator
# is most likely to be waiting on.
sleep "$DRAIN_SECONDS"

log "stopping ${ACTIVE}"
# Stopped, not removed. Rollback then costs one config flip instead of a rebuild.
$COMPOSE stop "$ACTIVE" || warn "could not stop ${ACTIVE}; it is idle either way"

log "restarting the bot onto the new image"
# The bot has no blue/green pair: it is a single long-poll/webhook consumer, and
# running two would deliver every Telegram update twice. A brief restart here is
# acceptable because Telegram retries undelivered webhook updates.
$COMPOSE up -d --no-deps bot || warn "the bot did not restart; check it manually"

log "deployed ${IDLE} successfully."
log "rollback if needed:  scripts/deploy.sh rollback"
