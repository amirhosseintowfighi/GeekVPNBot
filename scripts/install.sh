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
TELEGRAM__WEBHOOK_URL=https://${DOMAIN}/telegram/webhook
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

step "Creating the database schema"
EXISTING=$($COMPOSE exec -T postgres psql -U geekvpn -d geekvpn -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo 0)
if [[ "${EXISTING//[^0-9]/}" -gt 0 ]]; then
  die "This database already has ${EXISTING} tables. This wizard only installs onto an empty database; use scripts/deploy.sh to upgrade an existing one."
fi

$COMPOSE run --rm migrate alembic upgrade head
ok "schema created"

TABLES=$($COMPOSE exec -T postgres psql -U geekvpn -d geekvpn -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
ok "$(printf '%s' "${TABLES//[^0-9]/}") tables present"

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
  $COMPOSE exec -T nginx nginx -s reload >/dev/null 2>&1 || true
  ok "certificate issued for ${DOMAIN}"
  TLS_READY=1
else
  warn "Let's Encrypt could not issue a certificate yet."
  note "Almost always this means ${DOMAIN} does not resolve to this server."
  note "nginx is serving a self-signed placeholder until it does."
  TLS_READY=0
fi

step "Verifying"
sleep 3
if curl -fsS --max-time 10 "http://localhost/health/ready" >/dev/null 2>&1 \
   || curl -fsSk --max-time 10 "https://localhost/health/ready" >/dev/null 2>&1; then
  ok "the API reports ready"
else
  warn "readiness check did not pass yet. It is often just TLS still being issued."
  note "check with: $COMPOSE logs --tail=50 nginx api_blue"
fi

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

  Admin panel   https://${DOMAIN}/api/v1/admin
  Health        https://${DOMAIN}/health/ready
  Username      ${ADMIN_USER}

${BOLD}Do these three things now:${OFF}

  1. Back up ${ENV_FILE} somewhere off this machine. It holds the encryption
     master key, and every stored card number is unreadable without it.

  2. ${TLS_NOTE}

  3. Add your first VPN node in the admin panel, then press
     ${DIM}Test connection${OFF} on it. Nothing can be sold until a node exists and
     that button reports success - provisioning picks a node from the
     database, and an empty list means every paid order fails.

${BOLD}Useful:${OFF}

  logs      $COMPOSE logs -f api_blue
  status    $COMPOSE ps
  deploy    bash scripts/deploy.sh
  backup    bash scripts/backup.sh

EOF
