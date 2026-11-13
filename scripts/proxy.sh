#!/usr/bin/env bash
# One place to set the server's outbound proxy, and every tool follows it.
#
#   scripts/proxy.sh show            where a proxy is set today, and to what
#   scripts/proxy.sh set <url>       use <url> everywhere, replacing any other
#   scripts/proxy.sh off             no proxy anywhere on the host
#
# <url> is what the proxy speaks: socks5h://127.0.0.1:1080 for a local SOCKS
# client, http://127.0.0.1:8080 for an HTTP one, with user:pass@ if it needs it.
#
# Why this exists: a proxy written into one tool's config and forgotten keeps
# being used after it dies. On this server an old proxy was set separately for
# git and for the Docker daemon, so `git pull` and then the image build both
# hung on an address that no longer answered, each in its own way, each found
# only by its own error message. A proxy is a property of the server, not of
# one tool, so it is written to all of them from here and nowhere else.
#
# What it covers, and why each one:
#   - shells:      /etc/profile.d/geekvpn-proxy.sh (curl, pip, everything that
#                  reads http_proxy). Other definitions in /etc/environment,
#                  /etc/profile.d and root's shell files are commented out.
#   - git:         the global and system `http.proxy` / `https.proxy`.
#   - Docker:      the daemon's systemd drop-in, which is what pulls images
#                  and what BuildKit fetches the Dockerfile frontend through.
#                  `proxies` in daemon.json is removed so the two cannot differ.
#                  The daemon is restarted when this changes: running
#                  containers restart with it.
#   - Docker CLI:  `proxies` in ~/.docker/config.json is removed, not set. It
#                  copies the proxy into every build container, where
#                  127.0.0.1 is the container itself, so it can only break
#                  builds; they use PIP_INDEX_URL / NPM_REGISTRY instead.
#   - apt:         /etc/apt/apt.conf.d/95geekvpn-proxy.
#   - the app:     PROXY__URL in .env, on `set` only, with 127.0.0.1 rewritten
#                  to host.docker.internal - the address the containers reach
#                  the host by. `off` leaves it: from Iran the bot cannot reach
#                  Telegram without one, and that is a separate decision.
#
# Every file it edits is first copied, as it was, under /var/backups/geekvpn-proxy.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

PROFILE_FILE=/etc/profile.d/geekvpn-proxy.sh
DOCKER_DROPIN_DIR=/etc/systemd/system/docker.service.d
DOCKER_DROPIN="${DOCKER_DROPIN_DIR}/geekvpn-proxy.conf"
DOCKER_DAEMON_JSON=/etc/docker/daemon.json
DOCKER_CLIENT_JSON="${HOME}/.docker/config.json"
APT_FILE=/etc/apt/apt.conf.d/95geekvpn-proxy
APP_ENV="${PROJECT_DIR}/.env"
NO_PROXY_LIST="localhost,127.0.0.1,::1,host.docker.internal"
# Shell files a proxy is commonly exported from by hand.
SHELL_FILES=(/etc/environment /etc/bash.bashrc "${HOME}/.bashrc" "${HOME}/.profile" "${HOME}/.bash_profile")

log()  { printf '\033[0;36m[proxy]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[proxy]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[proxy]\033[0m %s\n' "$*" >&2; exit 1; }

# Credentials never reach the terminal: this output gets pasted into chats.
mask() { sed -E 's#(://)[^@/[:space:]]+@#\1***@#g'; }

# Kept outside the directories being edited: apt reads every file in
# apt.conf.d, so a backup beside the original would keep the old proxy live.
# Only the first copy is kept - it is the state before this script ever ran.
BACKUP_DIR=/var/backups/geekvpn-proxy
backup() {
  local copy="${BACKUP_DIR}$1"
  [[ -f "$1" && ! -f "$copy" ]] || return 0
  mkdir -p "$(dirname "$copy")"
  cp -p "$1" "$copy"
}

need_root() { [[ $EUID -eq 0 ]] || die "run as root (sudo $0 $*)"; }

# -- show ---------------------------------------------------------------------

show() {
  local found=0 file
  echo "== environment of this shell"
  if env | grep -iE '^(http|https|all|no)_proxy=' | mask; then found=1; fi

  echo "== shell files"
  for file in "${SHELL_FILES[@]}" /etc/profile.d/*.sh; do
    [[ -f "$file" ]] || continue
    if grep -HnE '^[[:space:]]*(export[[:space:]]+)?(http|https|all)_proxy=' -i "$file" | mask; then found=1; fi
  done

  echo "== git"
  if git config --show-origin --get-regexp '^https?\.proxy$' 2>/dev/null | mask; then found=1; fi
  if git config --system --get-regexp '^https?\.proxy$' 2>/dev/null | mask; then found=1; fi

  echo "== docker daemon"
  if [[ -d "$DOCKER_DROPIN_DIR" ]] && grep -HnEi 'proxy' "$DOCKER_DROPIN_DIR"/*.conf 2>/dev/null | mask; then found=1; fi
  if [[ -f "$DOCKER_DAEMON_JSON" ]] && grep -HnEi 'proxy' "$DOCKER_DAEMON_JSON" | mask; then found=1; fi
  if command -v systemctl >/dev/null && systemctl show docker --property=Environment 2>/dev/null \
      | grep -iE 'proxy' | mask; then found=1; fi

  echo "== docker client (build containers)"
  if [[ -f "$DOCKER_CLIENT_JSON" ]] && grep -HnEi 'proxy' "$DOCKER_CLIENT_JSON" | mask; then found=1; fi

  echo "== apt"
  if grep -HnEi '^[[:space:]]*Acquire::.*::Proxy' /etc/apt/apt.conf /etc/apt/apt.conf.d/* 2>/dev/null | mask; then found=1; fi

  echo "== the app (.env PROXY__URL, used by the bot for Telegram)"
  if [[ -f "$APP_ENV" ]]; then
    grep -E '^PROXY__URL=' "$APP_ENV" | mask || echo "(not set)"
  fi

  [[ $found -eq 1 ]] || echo "(no host-level proxy found)"
}

# -- the edits ----------------------------------------------------------------

# Comment out every other proxy definition in the shell files, so ours is the
# only one a new login reads.
clear_shell_files() {
  local file
  for file in "${SHELL_FILES[@]}" /etc/profile.d/*.sh; do
    [[ -f "$file" && "$file" != "$PROFILE_FILE" ]] || continue
    if grep -qiE '^[[:space:]]*(export[[:space:]]+)?(http|https|all|no)_proxy=' "$file"; then
      backup "$file"
      sed -i -E 's/^([[:space:]]*(export[[:space:]]+)?([Hh][Tt][Tt][Pp][Ss]?|[Aa][Ll][Ll]|[Nn][Oo])_[Pp][Rr][Oo][Xx][Yy]=)/# geekvpn: disabled, see scripts\/proxy.sh # \1/' "$file"
      log "disabled the proxy lines in $file"
    fi
  done
}

write_shell() {
  local url="$1"
  clear_shell_files
  if [[ -z "$url" ]]; then
    rm -f "$PROFILE_FILE"
    return
  fi
  umask 077
  cat >"$PROFILE_FILE" <<EOF
# Written by scripts/proxy.sh - change it there, not here.
export http_proxy='${url}' https_proxy='${url}' all_proxy='${url}'
export HTTP_PROXY='${url}' HTTPS_PROXY='${url}' ALL_PROXY='${url}'
export no_proxy='${NO_PROXY_LIST}' NO_PROXY='${NO_PROXY_LIST}'
EOF
  chmod 0644 "$PROFILE_FILE"
  log "shells: $PROFILE_FILE"
}

write_git() {
  local url="$1" scope
  for scope in --global --system; do
    git config "$scope" --unset-all http.proxy 2>/dev/null || true
    git config "$scope" --unset-all https.proxy 2>/dev/null || true
  done
  if [[ -n "$url" ]]; then
    git config --global http.proxy "$url"
    git config --global https.proxy "$url"
  fi
  log "git: ${url:-no proxy}"
}

# Returns 0 when the daemon's configuration changed and it needs a restart.
write_docker_daemon() {
  local url="$1" before after file
  before=$(cat "$DOCKER_DROPIN_DIR"/*.conf "$DOCKER_DAEMON_JSON" 2>/dev/null | md5sum || true)

  # Another drop-in that sets a proxy would be merged with ours by systemd,
  # and whichever comes last wins. Set aside, not deleted.
  for file in "$DOCKER_DROPIN_DIR"/*.conf; do
    [[ -f "$file" && "$file" != "$DOCKER_DROPIN" ]] || continue
    if grep -qi 'proxy' "$file"; then
      mv "$file" "$file.geekvpn-disabled"
      log "docker: set aside $file"
    fi
  done

  if [[ -f "$DOCKER_DAEMON_JSON" ]] && grep -qi '"proxies"' "$DOCKER_DAEMON_JSON"; then
    backup "$DOCKER_DAEMON_JSON"
    python3 - "$DOCKER_DAEMON_JSON" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
data.pop("proxies", None)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
    log "docker: removed proxies from $DOCKER_DAEMON_JSON"
  fi

  if [[ -n "$url" ]]; then
    # The daemon documents `socks5://` for a SOCKS proxy, and its dialer
    # hands the registry's name to the proxy either way, so `socks5h` would
    # only add a scheme it may not recognise.
    local daemon_url="${url/#socks5h:\/\//socks5://}"
    mkdir -p "$DOCKER_DROPIN_DIR"
    cat >"$DOCKER_DROPIN" <<EOF
# Written by scripts/proxy.sh - change it there, not here.
[Service]
Environment="HTTP_PROXY=${daemon_url}" "HTTPS_PROXY=${daemon_url}" "NO_PROXY=${NO_PROXY_LIST}"
EOF
    chmod 0600 "$DOCKER_DROPIN"
  else
    rm -f "$DOCKER_DROPIN"
  fi

  after=$(cat "$DOCKER_DROPIN_DIR"/*.conf "$DOCKER_DAEMON_JSON" 2>/dev/null | md5sum || true)
  [[ "$before" != "$after" ]]
}

write_docker_client() {
  [[ -f "$DOCKER_CLIENT_JSON" ]] && grep -qi '"proxies"' "$DOCKER_CLIENT_JSON" || return 0
  backup "$DOCKER_CLIENT_JSON"
  python3 - "$DOCKER_CLIENT_JSON" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
data.pop("proxies", None)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "docker client: removed proxies from $DOCKER_CLIENT_JSON"
}

write_apt() {
  local url="$1" file
  for file in /etc/apt/apt.conf /etc/apt/apt.conf.d/*; do
    [[ -f "$file" && "$file" != "$APT_FILE" ]] || continue
    if grep -qiE '^[[:space:]]*Acquire::.*::Proxy' "$file"; then
      backup "$file"
      sed -i -E 's/^([[:space:]]*Acquire::[^ ]*::Proxy)/\/\/ geekvpn: disabled, see scripts\/proxy.sh \/\/ \1/I' "$file"
      log "apt: disabled the proxy lines in $file"
    fi
  done
  if [[ -n "$url" ]]; then
    printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$url" "$url" >"$APT_FILE"
  else
    rm -f "$APT_FILE"
  fi
}

write_app() {
  local url="$1" app_url
  [[ -f "$APP_ENV" ]] || { warn "no .env at $APP_ENV; PROXY__URL not set"; return 0; }
  # Inside a container 127.0.0.1 is the container; the host is
  # host.docker.internal (mapped in docker-compose.prod.yml).
  app_url=$(printf '%s' "$url" | sed -E 's#(://([^@/]*@)?)(127\.0\.0\.1|localhost)([:/]|$)#\1host.docker.internal\4#')
  backup "$APP_ENV"
  if grep -qE '^PROXY__URL=' "$APP_ENV"; then
    python3 - "$APP_ENV" "$app_url" <<'PY'
import sys
path, value = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines()
lines = [f"PROXY__URL={value}" if l.startswith("PROXY__URL=") else l for l in lines]
open(path, "w").write("\n".join(lines) + "\n")
PY
  else
    printf '\nPROXY__URL=%s\n' "$app_url" >>"$APP_ENV"
  fi
  log "app: PROXY__URL=$(printf '%s' "$app_url" | mask) (takes effect on the next deploy)"
}

apply() {
  local url="$1"
  write_shell "$url"
  write_git "$url"
  write_docker_client
  write_apt "$url"
  if write_docker_daemon "$url"; then
    log "docker: restarting the daemon so it uses the new setting"
    systemctl daemon-reload
    systemctl restart docker
  else
    log "docker: daemon already uses this setting"
  fi
  [[ -n "$url" ]] && write_app "$url"
  warn "this shell still has the old variables. Run: exec bash -l"
}

# -- main ---------------------------------------------------------------------

case "${1:-show}" in
  show)
    show
    ;;
  set)
    need_root "$@"
    url="${2:-}"
    [[ "$url" =~ ^(socks5h?|http|https)://[^[:space:]]+:[0-9]+/?$ ]] \
      || die "usage: $0 set <socks5h|http>://[user:pass@]host:port"
    apply "${url%/}"
    log "done. Check with: $0 show"
    ;;
  off)
    need_root "$@"
    apply ""
    log "done: no host-level proxy. PROXY__URL in .env was left as it is."
    ;;
  *)
    die "usage: $0 show | set <url> | off"
    ;;
esac
