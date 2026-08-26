#!/usr/bin/env bash
# Restore an encrypted backup produced by scripts/backup.sh.
#
# This script is written to be run by a frightened person at four in the morning.
# That shapes every decision in it:
#
# 1. It refuses to run without an explicit --yes. A restore destroys the current
#    database. The one thing worse than needing a restore is performing one by
#    accident.
#
# 2. It takes a safety dump of the CURRENT database first. If the backup turns
#    out to be the wrong one, or older than believed, the state that existed
#    before the restore is still recoverable. This has saved more incidents than
#    the restore itself.
#
# 3. It stops the API before restoring and leaves it stopped. Restoring under a
#    live application produces a database that is half old and half new, and
#    nobody can tell which rows are which afterwards.
#
# 4. It verifies the checksum and decrypts to a temporary file before touching
#    anything, so a corrupt archive fails before the destructive step, not during.
#
# Usage:
#   scripts/restore.sh --file backups/geekvpn-...dump.gpg --yes
#   scripts/restore.sh --latest --yes
#   scripts/restore.sh --latest --dry-run
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
COMPOSE="${COMPOSE:-docker compose}"
PG_SERVICE="${PG_SERVICE:-postgres}"
DB_NAME="${POSTGRES__DB:-geekvpn}"
DB_USER="${POSTGRES__USER:-geekvpn}"
API_SERVICES="${API_SERVICES:-api_blue api_green bot}"

FILE=""
CONFIRMED=0
DRY_RUN=0

log() { printf '[restore] %s %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "FAILED: $*"; exit 1; }

usage() {
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

while (( $# )); do
  case "$1" in
    --file)    FILE="${2:?--file needs a path}"; shift 2 ;;
    --latest)  FILE=$(find "$BACKUP_DIR" -maxdepth 1 -name 'geekvpn-*.dump.gpg' -type f \
                        | sort | tail -1); shift ;;
    --yes)     CONFIRMED=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage 0 ;;
    *)         die "unknown argument: $1" ;;
  esac
done

[[ -n "$FILE" ]] || die "no backup selected; pass --file or --latest"
[[ -f "$FILE" ]] || die "no such file: $FILE"
[[ -n "${BACKUP_PASSPHRASE:-}" ]] || die "BACKUP_PASSPHRASE is required to decrypt"

AGE_SECONDS=$(( $(date -u +%s) - $(stat -c %Y "$FILE") ))
log "selected: $FILE"
log "size: $(wc -c < "$FILE") bytes, age: $(( AGE_SECONDS / 3600 )) hours"

# Checksum, if the sidecar exists. A silently corrupted archive that decrypts
# partway through is the failure mode this catches.
if [[ -f "${FILE}.sha256" ]]; then
  EXPECTED=$(cat "${FILE}.sha256")
  ACTUAL=$(sha256sum "$FILE" | awk '{print $1}')
  [[ "$EXPECTED" == "$ACTUAL" ]] || die "checksum mismatch; this archive is not intact"
  log "checksum verified"
else
  log "WARNING: no .sha256 sidecar; integrity is unverified"
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PLAIN="${WORK}/restore.dump"

log "decrypting"
gpg --batch --yes --quiet --decrypt --passphrase-fd 3 \
    --output "$PLAIN" "$FILE" 3<<<"$BACKUP_PASSPHRASE" \
  || die "decryption failed; wrong passphrase or corrupt archive"

log "inspecting the archive"
$COMPOSE exec -T "$PG_SERVICE" pg_restore --list < "$PLAIN" > "${WORK}/toc" \
  || die "the decrypted file is not a valid pg_dump archive"
TABLES=$(grep -c 'TABLE DATA' "${WORK}/toc" || true)
log "archive contains ${TABLES} tables"
(( TABLES > 10 )) || die "only ${TABLES} tables; refusing to restore over a live database"

if (( DRY_RUN )); then
  log "dry run: the archive is valid and restorable. Nothing was changed."
  grep 'TABLE DATA' "${WORK}/toc" | awk '{print "  " $NF}' | head -30 >&2
  exit 0
fi

if (( ! CONFIRMED )); then
  die "this will REPLACE the contents of database '${DB_NAME}'. Re-run with --yes"
fi

# ---------------------------------------------------------------------------
# Destructive from here on.
# ---------------------------------------------------------------------------
log "stopping application services: ${API_SERVICES}"
# shellcheck disable=SC2086
$COMPOSE stop ${API_SERVICES} || log "WARNING: could not stop every service; continuing"

SAFETY="${BACKUP_DIR}/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).dump"
log "taking a safety dump of the current database first: ${SAFETY}"
if $COMPOSE exec -T "$PG_SERVICE" \
     pg_dump --format=custom --compress=9 --no-owner --no-privileges \
             --username "$DB_USER" "$DB_NAME" > "$SAFETY"; then
  log "safety dump: $(wc -c < "$SAFETY") bytes"
else
  rm -f "$SAFETY"
  # Deliberately not fatal: the database may be too broken to dump, which is
  # often exactly why a restore is happening. But it must be stated loudly.
  log "WARNING: the safety dump failed. Proceeding means the current state is unrecoverable."
  read -r -p "Type PROCEED to continue: " answer
  [[ "$answer" == "PROCEED" ]] || die "aborted by operator"
fi

log "restoring"
# --clean --if-exists drops existing objects first. Without --if-exists the drop
# of an object the archive does not contain aborts the whole restore.
# --single-transaction so a failure leaves the database unchanged rather than
# half-restored. --exit-on-error for the same reason.
if $COMPOSE exec -T "$PG_SERVICE" \
     pg_restore --username "$DB_USER" --dbname "$DB_NAME" \
                --clean --if-exists --no-owner --no-privileges \
                --single-transaction --exit-on-error < "$PLAIN"; then
  log "restore completed"
else
  die "restore failed; the database was rolled back. The safety dump is at ${SAFETY}"
fi

# The extension must exist for the trigram indexes in migration 0004. It is
# created by the migration, but a restore from an older archive may predate it.
$COMPOSE exec -T "$PG_SERVICE" psql --username "$DB_USER" --dbname "$DB_NAME" \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;' >/dev/null 2>&1 || true

log "applying any migrations newer than the archive"
$COMPOSE run --rm migrate || die "migrations failed after the restore; the data is in place but the schema is behind"

log "restarting application services"
# shellcheck disable=SC2086
$COMPOSE start ${API_SERVICES} || die "services did not start"

log "done. Verify manually before announcing recovery:"
log "  - a recent order appears in the admin panel"
log "  - a customer can open the Mini App and see their subscription"
log "  - the safety dump is at ${SAFETY}; delete it once you are satisfied"
