#!/usr/bin/env bash
# Fresh install of Geek VPN on a clean server.
#
# This is for a NEW deployment with an empty database. It is not an upgrade
# path: it refuses to touch a database that already has tables, because the
# only safe thing to do with existing data is `scripts/deploy.sh`.
#
# On the schema: the wizard runs `alembic upgrade head` against the empty
# database. That IS the from-scratch install - it creates all 30 tables in one
# go. The tempting alternative, `Base.metadata.create_all`, would produce the
# same tables and leave Alembic with no version stamp, which quietly breaks
# every future upgrade. So the schema is created through Alembic even though
# there is nothing to migrate.
#
# Everything the wizard writes goes to .env, and it never overwrites an
# existing one without being told to.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
ENV_FILE=".env"

BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m')
GREEN=$(printf '\033[0;32m'); RED=$(printf '\033[0;31m')
YELLOW=$(printf '\033[0;33m'); CYAN=$(printf '\033[0;36m'); OFF=$(printf '\033[0m')

step()  { printf '\n%s==>%s %s%s%s\n' "$CYAN" "$OFF" "$BOLD" "$*" "$OFF"; }
ok()    { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
warn()  { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()   { printf '\n%serror:%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }
note()  { printf '  %s%s%s\n' "$DIM" "$*" "$OFF"; }

# ---------------------------------------------------------------- prompting

ask() {
  # ask <var> <prompt> [default]
  local __var=$1 __prompt=$2 __default=${3:-} __reply=""
  while true; do
    if [[ -n "$__default" ]]; then
      read -r -p "  ${__prompt} [${__default}]: " __reply || die "input closed"
      __reply=${__reply:-$__default}
    else
      read -r -p "  ${__prompt}: " __reply || die "input closed"
    fi
    [[ -n "$__reply" ]] && break
    warn "This one is required."
  done
  printf -v "$__var" '%s' "$__reply"
}

ask_secret() {
  # Reads without echoing, and requires the value twice. A mistyped admin
  # password on a fresh install is only discovered at the first sign-in.
  local __var=$1 __prompt=$2 __first="" __second=""
  while true; do
    read -r -s -p "  ${__prompt}: " __first; echo
    [[ ${#__first} -ge 12 ]] || { warn "At least 12 characters."; continue; }
    read -r -s -p "  ${__prompt} (again): " __second; echo
    [[ "$__first" == "$__second" ]] && break
    warn "They do not match."
  done
  printf -v "$__var" '%s' "$__first"
}

confirm() {
  local reply=""
  read -r -p "  $1 [y/N]: " reply || true
  [[ "$reply" =~ ^[Yy]$ ]]
}

# A 48-character URL-safe secret. Regenerated if it happens to contain a marker
# that the application's own weakness check rejects at boot - see
# infrastructure/security/secrets_provider.py.
gen_secret() {
  local candidate
  for _ in $(seq 1 16); do
    candidate=$(openssl rand -base64 64 | tr -d '\n=' | tr '+/' '-_' | cut -c1-48)
    if ! printf '%s' "$candidate" | grep -qiE 'insecure|do-not-use|example|sample|todo'; then
      printf '%s' "$candidate"; return 0
    fi
  done
  die "could not generate a secret"
}

# ------------------------------------------------------------ prerequisites

step "Checking prerequisites"

command -v docker >/dev/null || die "Docker is not installed. See https://get.docker.com"
docker compose version >/dev/null 2>&1 || die "The 'docker compose' plugin is missing."
docker info >/dev/null 2>&1 || die "Cannot talk to the Docker daemon. Is it running, and are you in the 'docker' group?"
command -v openssl >/dev/null || die "openssl is required to generate secrets."
ok "docker $(docker version --format '{{.Server.Version}}')"
ok "docker compose available"

if [[ -f "$ENV_FILE" ]]; then
  warn "$ENV_FILE already exists."
  confirm "Overwrite it? The current one will be saved as .env.backup" \
    || die "Nothing was changed. Delete or move $ENV_FILE and run again."
  cp "$ENV_FILE" ".env.backup"
  ok "backed up to .env.backup"
fi

# Postgres reads POSTGRES_PASSWORD only while its data directory is empty. A
# volume left behind by an earlier run therefore keeps that run's password
# forever, while this wizard generates a fresh one - so every later attempt
# fails authentication, and it fails inside alembic, long after the operator
# has answered every question. Checked here, before the first prompt.
PROJECT_NAME=$(basename "$PROJECT_DIR")
STALE_VOLUMES=$(docker volume ls -q --filter "name=postgres-data" --filter "name=redis-data" || true)
if [[ -n "$STALE_VOLUMES" ]]; then
  warn "Data volumes from an earlier run already exist:"
  printf '    %s\n' $STALE_VOLUMES
  note "Postgres still holds the password from the run that created its volume,"
  note "which this wizard has no way of knowing. A fresh install needs empty ones."
  confirm "Delete it, and everything in it, and install fresh?" \
    || die "Nothing was changed. To upgrade an existing deployment use scripts/deploy.sh, or remove the volumes yourself: docker volume rm $(printf '%s ' $STALE_VOLUMES)"
  # Plain docker, not $COMPOSE. Every compose invocation - `down` included -
  # interpolates the file first, and `${POSTGRES__PASSWORD:?...}` makes that
  # fail whenever .env is absent, which is precisely the state this runs in:
  # before the wizard has written one. Containers first; a volume in use
  # cannot be removed.
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT_NAME" \
    | xargs -r docker rm -f >/dev/null 2>&1 || true
  docker volume rm $STALE_VOLUMES >/dev/null \
    || die "Could not remove the volumes. Stop whatever is using them and run again."
  ok "volumes removed"
fi

# --------------------------------------------------------------- questions

step "Configuration"
note "Press Enter to accept a default shown in brackets."
echo

ask DOMAIN        "Domain that will serve the API (e.g. vpn.example.ir)"
ask CERTBOT_EMAIL "Email for Let's Encrypt renewal notices"
ask BOT_TOKEN     "Telegram bot token (from @BotFather)"
ask ADMIN_USER    "Administrator username" "admin"
ask_secret ADMIN_PASSWORD "Administrator password (min 12 chars)"

echo
ask ADMIN_IPS "Admin panel IP allowlist, comma separated (blank = allow any)" "none"
[[ "$ADMIN_IPS" == "none" ]] && ADMIN_IPS=""
ask MINIAPP_ORIGIN "Mini App / admin panel origin for CORS" "https://${DOMAIN}"

echo
note "Monitoring (Prometheus + Grafana + Alertmanager) needs a Telegram chat"
note "to send infrastructure alerts to. Leave blank to install without it."
ask ALERT_CHAT "Telegram chat id for alerts (blank = skip monitoring)" "none"
if [[ "$ALERT_CHAT" == "none" ]]; then
  ALERT_CHAT=""
  WITH_MONITORING=0
  note "monitoring will be skipped"
else
  WITH_MONITORING=1
fi

step "Generating secrets"
SECRET_KEY=$(gen_secret)
ENCRYPTION_KEY=$(gen_secret)
WEBHOOK_SECRET=$(gen_secret)
PG_PASSWORD=$(gen_secret)
# Production compose starts Redis with --requirepass and refuses an empty
# value, so this is required rather than optional.
REDIS_PASSWORD=$(gen_secret)
GRAFANA_PASSWORD=$(gen_secret)
ok "6 secrets generated (48 chars each, distinct)"
note "They are written to .env only. Back that file up somewhere safe."

# The production guardrail refuses to boot if these two match, because sharing
# one secret couples JWT rotation to re-encrypting every stored card number.
[[ "$SECRET_KEY" != "$ENCRYPTION_KEY" ]] || die "generated identical keys; run again"

# ----------------------------------------------------------------- write env

step "Writing $ENV_FILE"

umask 077
cat > "$ENV_FILE" <<EOF
# Generated by scripts/install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Treat this file as a credential. It is chmod 600 and git-ignored.

APP__NAME=Geek VPN
APP__ENV=production
APP__DEBUG=false
APP__BASE_URL=https://${DOMAIN}

LOGGING__LEVEL=INFO
LOGGING__JSON=true

POSTGRES__HOST=postgres
POSTGRES__PORT=5432
POSTGRES__USER=geekvpn
POSTGRES__PASSWORD=${PG_PASSWORD}
POSTGRES__DB=geekvpn
POSTGRES__POOL_SIZE=10
POSTGRES__MAX_OVERFLOW=20

REDIS__HOST=redis
REDIS__PORT=6379
REDIS__DB=0
REDIS__PASSWORD=${REDIS_PASSWORD}

TELEGRAM__BOT_TOKEN=${BOT_TOKEN}
TELEGRAM__WEBHOOK_SECRET=${WEBHOOK_SECRET}
TELEGRAM__WEBHOOK_PATH=/telegram/webhook
TELEGRAM__WEBHOOK_BASE_URL=https://${DOMAIN}
TELEGRAM__SET_WEBHOOK_ON_STARTUP=true

SECURITY__SECRET_KEY=${SECRET_KEY}
SECURITY__ENCRYPTION_MASTER_KEY=${ENCRYPTION_KEY}
SECURITY__CORS_ORIGINS=${MINIAPP_ORIGIN}
SECURITY__TRUSTED_PROXY_COUNT=1

AUTH__JWT_ISSUER=geekvpn
AUTH__JWT_AUDIENCE=geekvpn-clients
AUTH__ADMIN_IP_ALLOWLIST=${ADMIN_IPS}

# Deliberately absent: the production guardrail refuses to boot while a
# bootstrap password is set, and the wizard creates the administrator directly.

PRIMARY_DOMAIN=${DOMAIN}
CERTBOT_EMAIL=${CERTBOT_EMAIL}
GRAFANA_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
ALERT_TELEGRAM_CHAT_ID=${ALERT_CHAT}
ADMIN_ALLOW_CIDRS=${ADMIN_IPS}
POSTGRES_PASSWORD=${PG_PASSWORD}
EOF

chmod 600 "$ENV_FILE"
ok "$ENV_FILE written (mode 600)"

# ------------------------------------------------------------------ database

step "Building the application image"
# docker-compose.prod.yml pins these services to an image tag, and Compose only
# builds implicitly when that tag is missing. So the very first run built the
# image and every run after it silently reused the first one - source,
# migrations and all - which made a re-run after a code change look like the
# change had not worked. deploy.sh has always built explicitly; this did not.
note "The first build compiles dependencies and takes a few minutes."
$COMPOSE build migrate || die "image build failed"
ok "image built from the current checkout"

step "Starting Postgres and Redis"
$COMPOSE up -d postgres redis
ok "containers started"

printf '  waiting for Postgres'
for _ in $(seq 1 60); do
  if $COMPOSE exec -T postgres pg_isready -U geekvpn -d geekvpn >/dev/null 2>&1; then
    echo; ok "Postgres is accepting connections"; break
  fi
  printf '.'; sleep 2
done
$COMPOSE exec -T postgres pg_isready -U geekvpn -d geekvpn >/dev/null 2>&1 \
  || { echo; die "Postgres did not become ready. Check: $COMPOSE logs postgres"; }

# pg_isready does not authenticate - it only asks whether the server answers,
# so it reports success against a volume whose password we do not have. One
# real query, so a mismatch is one line here instead of a sixty-frame asyncpg
# traceback out of alembic.
$COMPOSE exec -T -e PGPASSWORD="$PG_PASSWORD" postgres \
  psql -U geekvpn -d geekvpn -tAc 'SELECT 1' >/dev/null 2>&1 \
  || die "Postgres rejected the generated password. Its data volume was created by an earlier run and kept that run's password. Start from an empty volume: $COMPOSE down -v"

# One helper, so every count authenticates and none of them can fail quietly.
# The two that used to be written inline had no PGPASSWORD and swallowed
# stderr, so a refused connection came back as the empty string: the
# "already has tables" guard read that as zero and waved every run through,
# and the count printed afterwards claimed a successful migration had created
# "0 tables".
count_tables() {
  $COMPOSE exec -T -e PGPASSWORD="$PG_PASSWORD" postgres psql -U geekvpn -d geekvpn -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'" \
    | tr -d '[:space:]'
}

step "Creating the database schema"
EXISTING=$(count_tables) || die "Could not query the database. Check: $COMPOSE logs postgres"
[[ "$EXISTING" =~ ^[0-9]+$ ]] \
  || die "The table count came back as '${EXISTING}', which is not a number. Check: $COMPOSE logs postgres"
if [[ "$EXISTING" -gt 0 ]]; then
  die "This database already has ${EXISTING} tables. This wizard only installs onto an empty database; use scripts/deploy.sh to upgrade an existing one."
fi

$COMPOSE run --rm migrate alembic upgrade head
ok "schema created"

# A migration that reports success and leaves nothing behind is not a success.
TABLES=$(count_tables)
[[ "$TABLES" =~ ^[0-9]+$ && "$TABLES" -gt 0 ]] \
  || die "alembic reported success but the schema has ${TABLES:-no} tables. Check: $COMPOSE logs postgres"
ok "$TABLES tables present"

# ------------------------------------------------------------------- admin

step "Creating the administrator"
# create_admin reads GEEKVPN_ADMIN_PASSWORD. Without it the tool falls back to
# getpass, which has no terminal inside `compose run` and would hang the install.
$COMPOSE run --rm -e GEEKVPN_ADMIN_PASSWORD="$ADMIN_PASSWORD" migrate \
  python -m geekvpn.entrypoints.create_admin --username "$ADMIN_USER"
ok "administrator '$ADMIN_USER' created"

# ------------------------------------------------------------------- launch

step "Starting the platform"
WITH_MONITORING="$WITH_MONITORING" bash scripts/deploy.sh
ok "services started"

# -------------------------------------------------------------------- check

step "Requesting a TLS certificate"
# The certbot service only ever runs `certbot renew`, which is a no-op until a
# certificate exists. Nothing else issues the first one, so without this step
# the site would serve the entrypoint's self-signed placeholder forever.
#
# This deliberately does not abort the install when it fails: the usual reason
# is that DNS does not point here yet, which is not something the installer can
# fix, and everything else is already working by this point.
if $COMPOSE run --rm --entrypoint certbot certbot      certonly --webroot --webroot-path=/var/www/certbot      -d "$DOMAIN" --email "$CERTBOT_EMAIL"      --agree-tos --no-eff-email --non-interactive 2>&1 | tail -5
then
  # Recreated, not reloaded. Which directory nginx reads its certificate from is
  # decided by the entrypoint, and a reload does not re-run it - so a reload
  # here would leave nginx serving the self-signed placeholder with a valid
  # certificate sitting on disk beside it.
  $COMPOSE up -d --force-recreate nginx >/dev/null 2>&1 || true
  ok "certificate issued for ${DOMAIN}"
  # The bot started before this certificate existed, so Telegram refused its
  # webhook registration - which is logged and survived, not fatal. This is the
  # first moment the URL is actually reachable over valid TLS, so give it the
  # one restart that makes the registration stick.
  $COMPOSE up -d --no-deps --force-recreate bot >/dev/null 2>&1 \
    && ok "bot restarted; webhook registered against the new certificate" \
    || warn "the bot did not restart; register the webhook by restarting it manually"
  TLS_READY=1
else
  warn "Let's Encrypt could not issue a certificate yet."
  note "Almost always this means ${DOMAIN} does not resolve to this server."
  note "nginx is serving a self-signed placeholder until it does."
  TLS_READY=0
fi

step "Verifying"
sleep 3
# Through nginx's internal check, the same one deploy.sh uses. The previous
# version curled http://localhost/health/ready without -L: that request is
# answered with a 301 to HTTPS, and `curl -f` only fails from 400 upwards, so
# it reported "the API reports ready" on a redirect it never followed. It
# passed whether or not anything behind nginx was alive.
if $COMPOSE exec -T nginx wget -qO- -T 10 http://127.0.0.1/edge-check >/dev/null 2>&1; then
  ok "the API answers through nginx"
else
  warn "the API did not answer through nginx."
  note "check with: $COMPOSE logs --tail=50 nginx api_green"
fi

# Whichever colour deploy.sh left serving. Printing a hardcoded api_blue sent
# every operator to the logs of the container it had just stopped.
LIVE_COLOUR=$(grep -oE 'api_(blue|green)' docker/nginx/conf.d/active-api.conf | head -1)
LIVE_COLOUR=${LIVE_COLOUR:-api_green}

if [[ "${TLS_READY:-0}" == "1" ]]; then
  TLS_NOTE="TLS is live for ${DOMAIN}, and certbot will keep it renewed."
else
  TLS_NOTE="Point ${DOMAIN} at this server, then issue the certificate:
       ${DIM}$COMPOSE run --rm --entrypoint certbot certbot certonly \
         --webroot --webroot-path=/var/www/certbot -d ${DOMAIN} \
         --email ${CERTBOT_EMAIL} --agree-tos --no-eff-email --non-interactive${OFF}
     Until then nginx serves the self-signed placeholder it generated."
fi

cat <<EOF

${GREEN}${BOLD}Installation complete.${OFF}

  Admin API     https://${DOMAIN}/api/v1/admin/auth/login  ${DIM}(POST, not a web page)${OFF}
  Health        https://${DOMAIN}/health/ready
  Username      ${ADMIN_USER}

  ${YELLOW}The admin panel and Mini App are Next.js applications in admin/ and
  miniapp/. This stack has no service for either, so nothing serves them
  yet and their hostnames answer 502. Only the API and the bot are running.${OFF}

${BOLD}Do these three things now:${OFF}

  1. Back up ${ENV_FILE} somewhere off this machine. It holds the encryption
     master key, and every stored card number is unreadable without it.

  2. ${TLS_NOTE}

  3. Add your first VPN node, through the admin API, and confirm it
     connects. Nothing can be sold until a node exists - provisioning picks
     one from the database, and an empty list means every paid order fails.

${BOLD}Useful:${OFF}

  logs      $COMPOSE logs -f ${LIVE_COLOUR}
  status    $COMPOSE ps
  deploy    bash scripts/deploy.sh
  backup    bash scripts/backup.sh

EOF
