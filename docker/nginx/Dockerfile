# syntax=docker/dockerfile:1.7
# The stable line. 1.27 stopped being rebuilt, so its Alpine base kept
# accumulating fixed-but-unshipped CVEs (expat, libpng, libxml2, musl, ...).
ARG NGINX_VERSION=1.30
FROM nginx:${NGINX_VERSION}-alpine

# openssl for the bootstrap self-signed certificate and the DH parameters;
# gettext for envsubst. The official alpine image ships a trimmed envsubst that
# does not accept a variable allowlist, and without that allowlist templating
# would silently blank every nginx variable in the config.
#
# `apk upgrade` because a base tag is only as fresh as its last rebuild; this
# picks up security fixes published since then.
#
# curl is removed: nothing here uses it (healthchecks use busybox wget), and
# the base image's copy is a standing source of HIGH CVEs that fail the scan.
RUN apk upgrade --no-cache && apk add --no-cache openssl gettext && apk del --no-cache curl

COPY nginx.conf /etc/nginx/nginx.conf
COPY snippets/ /etc/nginx/snippets/
COPY conf.d/00-upstreams.conf /etc/nginx/conf.d/00-upstreams.conf
COPY conf.d/active-api.conf /etc/nginx/conf.d/active-api.conf
COPY templates/geekvpn.conf /etc/nginx/templates/geekvpn.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /etc/nginx/tls /var/www/certbot

EXPOSE 80 443

# Overrides the base image's entrypoint on purpose: that one runs its own
# templating pass over /etc/nginx/templates with an unrestricted envsubst.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
