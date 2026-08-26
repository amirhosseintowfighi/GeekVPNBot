#!/bin/sh
# Nginx entrypoint: render the runtime-variable parts of the config, verify it,
# then exec nginx.
#
# Why templating at all, rather than baking domains into the image: the same
# image must run in staging and production. An image that contains a hostname is
# an image that cannot be promoted, so "the thing we tested" and "the thing we
# shipped" stop being identical.
#
# Only two things are templated - domains and the admin allowlist. Everything
# else is static config, reviewed in git.
set -eu

: "${PRIMARY_DOMAIN:?PRIMARY_DOMAIN is required}"
ADMIN_DOMAIN="${ADMIN_DOMAIN:-admin.${PRIMARY_DOMAIN}}"
MINIAPP_DOMAIN="${MINIAPP_DOMAIN:-app.${PRIMARY_DOMAIN}}"
ADMIN_ALLOW_CIDRS="${ADMIN_ALLOW_CIDRS:-}"
export PRIMARY_DOMAIN ADMIN_DOMAIN MINIAPP_DOMAIN

# A self-signed stand-in, used only until certbot has issued the real thing.
# Without it nginx refuses to start, and without nginx running the ACME HTTP-01
# challenge cannot be answered - a deadlock on every fresh install.
#
# It must NOT be written into /etc/letsencrypt/live/. That is certbot's own
# lineage directory, on a volume certbot shares, and certbot refuses to issue a
# certificate for a name whose live directory already exists without a matching
# renewal config: "live directory exists for <domain>". So the placeholder that
# exists to break the deadlock created a permanent one instead - the first
# certificate could never be issued, on any install, no matter how correct DNS
# was. TLS then stayed self-signed, and Telegram will not register a webhook
# against that, so the bot never came up either.
LIVE_DIR="/etc/letsencrypt/live/${PRIMARY_DOMAIN}"
FALLBACK_DIR="/etc/nginx/tls/selfsigned"

if [ -f "${LIVE_DIR}/fullchain.pem" ]; then
  SSL_DIR="$LIVE_DIR"
else
  echo "nginx-entrypoint: no certificate for ${PRIMARY_DOMAIN}; serving a temporary self-signed one" >&2
  mkdir -p "$FALLBACK_DIR"
  if [ ! -f "${FALLBACK_DIR}/fullchain.pem" ]; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
      -keyout "${FALLBACK_DIR}/privkey.pem" \
      -out "${FALLBACK_DIR}/fullchain.pem" \
      -subj "/CN=${PRIMARY_DOMAIN}" >/dev/null 2>&1
    cp "${FALLBACK_DIR}/fullchain.pem" "${FALLBACK_DIR}/chain.pem"
  fi
  SSL_DIR="$FALLBACK_DIR"
fi
export SSL_DIR
echo "nginx-entrypoint: serving TLS from ${SSL_DIR}" >&2

TEMPLATE=/etc/nginx/templates/geekvpn.conf
TARGET=/etc/nginx/conf.d/geekvpn.conf

# ---------------------------------------------------------------------------
# Upstream pools for the front-ends.
#
# A `proxy_pass` that names its target through a variable defers resolution to
# request time. That is what lets this edge start while a blue/green colour is
# stopped - but it also means nginx re-resolves the name every time its 
# resolver cache expires, in the middle of a live request, with no retry: a
# single failed lookup is a 502 the customer sees. Both front-ends did exactly
# that, on the first page load after any quiet period:
#
#     admin could not be resolved (3: Host not found)
#
# Nginx matches a variable target against defined upstream groups first, and
# only falls back to the resolver when no group has that name. So a pool
# removes request-time DNS for these two without touching the variable
# mechanism the API colours still need - and adds keepalive, which the
# resolver path cannot have and which is worth most exactly here, where one
# page load pulls dozens of chunks.
#
# The pool is only written when the name resolves *now*, at container start.
# Nginx refuses to load a config naming an upstream it cannot resolve, and an
# edge that will not start because an optional container is absent is the
# failure this whole file was built to avoid. Absent means the variable path,
# same as before.
POOLS=/etc/nginx/conf.d/10-frontend-pools.conf
: > "$POOLS"
echo "# Generated at container start. See entrypoint.sh." >> "$POOLS"

pool_for() {  # name host port  ->  echoes the proxy_pass target
  if getent hosts "$2" >/dev/null 2>&1; then
    printf 'upstream %s {\n    server %s:%s max_fails=0;\n    keepalive 16;\n}\n' \
      "$1" "$2" "$3" >> "$POOLS"
    echo "$1"
  else
    echo "nginx-entrypoint: $2 does not resolve; leaving it on request-time DNS" >&2
    echo "$2:$3"
  fi
}

MINIAPP_TARGET=$(pool_for miniapp_pool miniapp 3000)
ADMIN_TARGET=$(pool_for admin_pool admin 3001)
export MINIAPP_TARGET ADMIN_TARGET

# Substitute only our own names. A bare `envsubst` with no variable list would
# also eat every nginx variable - $host, $request_uri, $active_api - and replace
# them with empty strings, producing a config that is valid and completely wrong.
envsubst '${PRIMARY_DOMAIN} ${ADMIN_DOMAIN} ${MINIAPP_DOMAIN} ${SSL_DIR} ${MINIAPP_TARGET} ${ADMIN_TARGET}' < "$TEMPLATE" > "$TARGET"

# Render the admin allowlist.
ALLOW_FILE=/etc/nginx/conf.d/admin-allow.conf
{
  echo "# Generated at container start from ADMIN_ALLOW_CIDRS."
  if [ -n "$ADMIN_ALLOW_CIDRS" ]; then
    echo "$ADMIN_ALLOW_CIDRS" | tr ',' '\n' | while read -r cidr; do
      cidr=$(echo "$cidr" | tr -d ' ')
      [ -n "$cidr" ] && echo "allow $cidr;"
    done
    # The deny must come last: nginx evaluates allow/deny in order and stops at
    # the first match, so a leading deny would refuse everyone.
    echo "deny all;"
  else
    echo "# ADMIN_ALLOW_CIDRS is empty - the application-level allowlist is the only gate."
  fi
} > "$ALLOW_FILE"


if [ ! -f /etc/nginx/tls/dhparam.pem ]; then
  # 2048 bits, not 4096: generation is slow and this only affects the legacy
  # non-ECDHE path, which the cipher list does not offer anyway.
  mkdir -p /etc/nginx/tls
  openssl dhparam -out /etc/nginx/tls/dhparam.pem 2048 >/dev/null 2>&1
fi

# Fail here, loudly, rather than exec into a broken nginx.
nginx -t

exec nginx -g 'daemon off;'
