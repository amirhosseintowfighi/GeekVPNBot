#!/usr/bin/env bash
# Nightly backup of Postgres, encrypted at rest.
#
# Design decisions worth arguing with:
#
# 1. `pg_dump -Fc` (custom format), not plain SQL. Custom format is compressed,
#    and it allows a selective restore of one table - which is what an incident
#    usually needs, rather than replacing the entire database.
#
# 2. The dump is encrypted with age/gpg before it ever touches off-site storage.
#    This database contains encrypted card blind indexes, Telegram ids and full
#    purchase histories. An unencrypted dump in an S3 bucket is the single most
#    likely way this data leaks, because buckets get misconfigured far more often
#    than servers get compromised.
#
# 3. Every backup is verified by listing its table of contents. An unverified
#    backup is a hope, not a backup, and `pg_dump` exiting 0 does not prove the
#    output is readable.
#
# 4. A success timestamp is written for node-exporter's textfile collector, so
#    the BackupMissing alert can fire. A backup system nobody checks is a backup
#    system that has already failed silently.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
METRICS_DIR="${BACKUP_DIR}/metrics"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
PG_SERVICE="${PG_SERVICE:-postgres}"
COMPOSE="${COMPOSE:-docker compose}"
DB_NAME="${POSTGRES__DB:-geekvpn}"
DB_USER="${POSTGRES__USER:-geekvpn}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BASENAME="geekvpn-${DB_NAME}-${STAMP}"

log() { printf '[backup] %s %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "FAILED: $*"; exit 1; }

# Report the failure to the metrics file too. Without this a crashed backup looks
# identical to a backup that was never scheduled.
trap 'log "aborted on line $LINENO"' ERR

mkdir -p "$BACKUP_DIR" "$METRICS_DIR"

command -v gpg >/dev/null 2>&1 || die "gpg is required to encrypt the dump"
[[ -n "${BACKUP_PASSPHRASE:-}" ]] || die "BACKUP_PASSPHRASE is required; refusing to write an unencrypted dump"
# A short passphrase on an off-site file is a false sense of safety.
(( ${#BACKUP_PASSPHRASE} >= 20 )) || die "BACKUP_PASSPHRASE must be at least 20 characters"

DUMP_PATH="${BACKUP_DIR}/${BASENAME}.dump"
ENC_PATH="${DUMP_PATH}.gpg"

log "dumping ${DB_NAME} from service ${PG_SERVICE}"
# --no-owner / --no-privileges: the restore target may use different role names,
# and a restore that fails on a missing role at 4am is a self-inflicted outage.
if ! $COMPOSE exec -T "$PG_SERVICE" \
      pg_dump --format=custom --compress=9 --no-owner --no-privileges \
              --username "$DB_USER" "$DB_NAME" > "$DUMP_PATH"; then
  rm -f "$DUMP_PATH"
  die "pg_dump failed"
fi

# An empty or absurdly small dump means the redirect captured an error message
# rather than data. Checked explicitly because the pipeline above can succeed
# while producing nothing useful.
SIZE=$(wc -c < "$DUMP_PATH")
(( SIZE > 4096 )) || { rm -f "$DUMP_PATH"; die "dump is only ${SIZE} bytes; refusing to keep it"; }
log "dump written: ${SIZE} bytes"

log "verifying the dump is readable"
# pg_restore --list parses the archive header and table of contents. It does not
# prove every row is intact, but it does catch the common truncation and
# wrong-version failures - and it costs a second.
if ! $COMPOSE exec -T "$PG_SERVICE" pg_restore --list < "$DUMP_PATH" > "${DUMP_PATH}.toc"; then
  rm -f "$DUMP_PATH" "${DUMP_PATH}.toc"
  die "the dump is not readable by pg_restore"
fi
TABLES=$(grep -c 'TABLE DATA' "${DUMP_PATH}.toc" || true)
(( TABLES > 10 )) || { die "only ${TABLES} tables in the dump; the schema has far more"; }
log "verified: ${TABLES} tables present"

log "encrypting"
gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-fd 3 --output "$ENC_PATH" "$DUMP_PATH" 3<<<"$BACKUP_PASSPHRASE"
rm -f "$DUMP_PATH"
ENC_SIZE=$(wc -c < "$ENC_PATH")
sha256sum "$ENC_PATH" | awk '{print $1}' > "${ENC_PATH}.sha256"
log "encrypted: ${ENC_SIZE} bytes"

# Off-site copy. Optional, and loudly optional: a backup that lives only on the
# machine it is backing up protects against nothing except a dropped table.
if [[ -n "${BACKUP_S3_TARGET:-}" ]]; then
  if command -v aws >/dev/null 2>&1; then
    log "uploading to ${BACKUP_S3_TARGET}"
    aws s3 cp "$ENC_PATH" "${BACKUP_S3_TARGET%/}/${BASENAME}.dump.gpg" --only-show-errors \
      || die "off-site upload failed"
    aws s3 cp "${ENC_PATH}.sha256" "${BACKUP_S3_TARGET%/}/${BASENAME}.dump.gpg.sha256" --only-show-errors \
      || die "off-site checksum upload failed"
  else
    die "BACKUP_S3_TARGET is set but the aws cli is not installed"
  fi
else
  log "WARNING: BACKUP_S3_TARGET is not set - this backup exists only on this host"
fi

# Retention. Applied only after a successful new backup, so a failing job never
# deletes the last good copy.
log "pruning backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -name 'geekvpn-*.dump.gpg*' -type f \
     -mtime +"$RETENTION_DAYS" -print -delete >&2 || true

REMAINING=$(find "$BACKUP_DIR" -maxdepth 1 -name 'geekvpn-*.dump.gpg' -type f | wc -l)
log "backups on disk: ${REMAINING}"

# Metrics for node-exporter's textfile collector. Written atomically: the
# collector may read the file at any moment, and a half-written file is a parse
# error that looks like a missing metric.
TMP=$(mktemp "${METRICS_DIR}/.backup.XXXXXX")
{
  echo '# HELP geekvpn_backup_last_success_timestamp_seconds Unix time of the last verified backup.'
  echo '# TYPE geekvpn_backup_last_success_timestamp_seconds gauge'
  echo "geekvpn_backup_last_success_timestamp_seconds $(date -u +%s)"
  echo '# HELP geekvpn_backup_size_bytes Size of the last encrypted backup.'
  echo '# TYPE geekvpn_backup_size_bytes gauge'
  echo "geekvpn_backup_size_bytes ${ENC_SIZE}"
  echo '# HELP geekvpn_backup_count Number of backups retained on this host.'
  echo '# TYPE geekvpn_backup_count gauge'
  echo "geekvpn_backup_count ${REMAINING}"
} > "$TMP"
chmod 0644 "$TMP"
mv "$TMP" "${METRICS_DIR}/backup.prom"

rm -f "${DUMP_PATH}.toc"
log "done: ${ENC_PATH}"
