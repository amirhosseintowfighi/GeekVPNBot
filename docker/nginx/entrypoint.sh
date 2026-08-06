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

TEMPLATE=/etc/nginx/templates/geekvpn.conf
TARGET=/etc/nginx/conf.d/geekvpn.conf

# Substitute only our three names. A bare `envsubst` with no variable list would
# also eat every nginx variable - $host, $request_uri, $active_api - and replace
# them with empty strings, producing a config that is valid and completely wrong.
envsubst '${PRIMARY_DOMAIN} ${ADMIN_DOMAIN} ${MINIAPP_DOMAIN}' < "$TEMPLATE" > "$TARGET"

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

# A self-signed stand-in, used only until certbot has issued the real thing.
# Without it nginx refuses to start, and without nginx running the ACME HTTP-01
# challenge cannot be answered - a deadlock on every fresh install.
LIVE_DIR="/etc/letsencrypt/live/${PRIMARY_DOMAIN}"
if [ ! -f "${LIVE_DIR}/fullchain.pem" ]; then
  echo "nginx-entrypoint: no certificate for ${PRIMARY_DOMAIN}; generating a temporary self-signed one" >&2
  mkdir -p "$LIVE_DIR"
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "${LIVE_DIR}/privkey.pem" \
    -out "${LIVE_DIR}/fullchain.pem" \
    -subj "/CN=${PRIMARY_DOMAIN}" >/dev/null 2>&1
  cp "${LIVE_DIR}/fullchain.pem" "${LIVE_DIR}/chain.pem"
fi

if [ ! -f /etc/nginx/tls/dhparam.pem ]; then
  # 2048 bits, not 4096: generation is slow and this only affects the legacy
  # non-ECDHE path, which the cipher list does not offer anyway.
  mkdir -p /etc/nginx/tls
  openssl dhparam -out /etc/nginx/tls/dhparam.pem 2048 >/dev/null 2>&1
fi

# Fail here, loudly, rather than exec into a broken nginx.
nginx -t

exec nginx -g 'daemon off;'
