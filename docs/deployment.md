# Deployment

This document describes how GeekVPN runs in production: what the topology is, how
a release reaches customers without downtime, and which parts are deliberately
manual. Incident response lives in [runbook.md](runbook.md).

---

## 1. Topology

```
                    internet
                       |
                    :443 TLS
                       v
              +------------------+
              |      nginx       |  own image: TLS config, templating entrypoint
              +------------------+
                 |   |   |    |
     $active_api |   |   |    +---> miniapp  :3000   (app.<domain>)
           +-----+   |   +--------> admin    :3001   (admin.<domain>)
           |         +------------> bot      :8081   (webhook path only)
           v
   +--------------+   +--------------+
   |  api_blue    |   |  api_green   |   exactly one receives traffic
   +--------------+   +--------------+
           \               /
            v             v
        +----------+  +--------+
        | postgres |  | redis  |     network `backend`, internal: true
        +----------+  +--------+
                |          |
           exporters -> prometheus -> alertmanager -> Telegram
                            |
                         grafana        network `monitoring`, internal: true
```

**Only nginx is reachable from the internet.** Postgres, Redis, Prometheus,
Alertmanager and Grafana publish no ports at all, and the `backend` and
`monitoring` networks are `internal: true`. A `deploy_gate.py` check fails the
build if a datastore or monitoring UI ever gains a `ports:` entry, because that is
the kind of change that looks harmless in a diff.

Grafana is reached through an SSH tunnel:

```bash
ssh -L 3000:localhost:3000 <host>    # http://localhost:3000/grafana/
```

### Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Base definition, shared by every environment |
| `docker-compose.dev.yml` | Local development: exposed ports, bind mounts, `--reload` |
| `docker-compose.prod.yml` | Production: both API colours, tuned Postgres, certbot |
| `docker-compose.monitoring.yml` | Prometheus, Alertmanager, Grafana, three exporters |
| `docker/nginx/` | Edge image, TLS snippets, upstreams, server templates |
| `docker/monitoring/` | Scrape config, 14 alert rules, provisioned dashboard |
| `scripts/deploy.sh` | Blue/green deploy, rollback, status |
| `scripts/backup.sh` | Encrypted, verified dump + retention + metrics |
| `scripts/restore.sh` | Restore with a safety dump and an explicit `--yes` |
| `scripts/deploy_gate.py` | Consistency gate over all of the above |

---

## 2. First-time setup

### 2.1 Prerequisites

A host with Docker Engine 24+ and the compose plugin, 2 vCPU and 4 GB RAM as a
realistic minimum, and DNS `A` records for three names pointing at it:
`<domain>`, `admin.<domain>`, `app.<domain>`.

The DNS records must resolve **before** the first start, because Let's Encrypt
validates over HTTP.

### 2.2 Configuration

```bash
cp .env.example .env
```

Every variable is documented in `.env.example`. These have no safe default and the
application refuses to start without them in production:

| Variable | Notes |
| --- | --- |
| `SECURITY__SECRET_KEY` | 32+ chars. Signs tokens and the CSRF cookie |
| `SECURITY__ENCRYPTION_MASTER_KEY` | 32+ chars, **must differ** from the above |
| `POSTGRES__PASSWORD` | |
| `REDIS__PASSWORD` | |
| `TELEGRAM__BOT_TOKEN` | |
| `PRIMARY_DOMAIN`, `ADMIN_DOMAIN`, `MINIAPP_DOMAIN` | |
| `CERTBOT_EMAIL` | The only warning you get if renewal starts failing |
| `GRAFANA_ADMIN_PASSWORD` | The image otherwise defaults to `admin`/`admin` |
| `BACKUP_PASSPHRASE` | 20+ chars. `backup.sh` refuses to run without it |
| `ALERT_TELEGRAM_CHAT_ID` | A **private** group, not a customer chat |

Generate secrets with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(36))"
```

The two keys must be different. Sharing one couples their rotation permanently:
you could never rotate the token key without re-encrypting every stored card
number. `settings.py` enforces this at start-up rather than trusting the operator
to remember.

### 2.3 Validate before starting anything

```bash
make verify-config
```

This runs the deployment gate, `docker compose config` over the production and
monitoring overlays, `bash -n` over every script, and the SQL injection gate.

### 2.4 First boot

```bash
make prod-up
```

The nginx entrypoint resolves the chicken-and-egg problem that stops most first
deploys: nginx will not start without a certificate, and ACME validation cannot
succeed without nginx running. It generates a **one-day self-signed certificate**
so nginx starts immediately, then certbot replaces it with a real one. Expect a
browser warning for the first few minutes; if it persists, check the certbot logs.

Then create the first administrator:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm api_blue python -m geekvpn.entrypoints.create_admin
```

### 2.5 Schedule backups

**The compose stack does not schedule backups.** This is a host-level cron entry
and it is a manual step on purpose - a backup job hidden inside the application
stack stops when the stack does, which is exactly when you need it.

```cron
17 2 * * * cd /srv/geekvpn && ./scripts/backup.sh >> /var/log/geekvpn-backup.log 2>&1
```

The `BackupMissing` alert fires after 36 hours without a verified backup, so
forgetting this step is noisy rather than silent.

---

## 3. Deploying a release

```bash
make deploy         # runs the gate first, then blue/green
make deploy-status  # which colour is serving
make rollback       # flip back, about one second
```

### What `deploy.sh` actually does

1. Reads the active colour from `docker/nginx/conf.d/active-api.conf` - the same
   file nginx reads. There is deliberately no second source of truth.
2. Builds the new image.
3. Runs migrations, **while the old colour is still serving**.
4. Starts the idle colour and waits for its container health check, which is
   `/health/ready` and therefore includes Postgres and Redis.
5. Smoke tests the new colour directly, bypassing nginx: readiness plus
   `/metrics` containing `geekvpn_build_info`. The second check proves the
   middleware stack assembled, not merely that a socket is open.
6. Rewrites one line in `active-api.conf`, runs `nginx -t`, then `nginx -s reload`.
   Existing connections finish on the old workers; nothing is cut off.
7. Verifies through the edge. **If this fails it flips back automatically.**
8. Drains for 15 seconds, then stops the old colour - stopped, not removed, so
   rollback stays a one-second config flip.
9. Restarts the bot onto the new image.

### The constraint this design imposes

**Migrations run while both versions may be live, so every migration must be
backwards compatible with the currently deployed code.**

- Adding a nullable column, a table, or an index: safe.
- Renaming or dropping a column, or adding a `NOT NULL` column without a default:
  **not safe**. The old code, still serving traffic, breaks.

Drops and renames take two releases: stop using the column, deploy, then remove it
in the next release. This is invisible in staging, where only one version ever
runs, which is precisely why it is written down here.

### Why the bot has no blue/green pair

It is a single consumer of Telegram updates. Running two would deliver every
update twice - double notifications, double command handling. It takes a brief
restart instead, which is acceptable because Telegram retries undelivered webhook
updates.

---

## 4. CI/CD

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | Contents |
| --- | --- |
| `quality` | ruff lint, ruff format, mypy strict, import-linter |
| `security` | SQLi gate, deployment gate, `pip-audit`, bandit, gitleaks |
| `test` | Postgres + Redis services, migrations, pytest with coverage |
| `docker` | Build + Trivy scan for **both** images, plus `nginx -t` in the built image |
| `compose` | dev, prod and monitoring overlays validate; `promtool check rules` |

`.github/workflows/deploy.yml` runs on a `v*` tag: build and push once to GHCR,
attach a provenance attestation, deploy to staging, smoke test, then **wait for a
reviewer** on the `production` GitHub Environment. Production takes a database
backup before migrating, then runs the same `scripts/deploy.sh` an operator would
run by hand - CI has no separate deployment path, because a rehearsal that differs
from the real thing rehearses nothing.

The build job refuses to ship a commit whose CI checks failed, which closes the
usual hole of a tag pushed onto a red branch.

---

## 5. Monitoring

14 alert rules in four groups - availability, business, security, infrastructure -
deliver to a private Telegram group. Every rule carries a Persian summary, an
English description and a `runbook` link, and `deploy_gate.py` fails the build if
any rule references a metric the application does not register. An alert that
queries a non-existent metric is permanently silent while looking like coverage,
which is worse than having no alert at all.

Two rules are worth knowing about before an incident:

- **`RateLimiterUnusuallyQuiet`** is inverted: it fires when there are *zero* rate
  limit refusals in an hour. The limiter fails open when Redis is unavailable, so a
  Redis outage silently disables every rate limit. Nothing else would tell you.
- **`PaymentReviewBacklog`** is a revenue alert, not an infrastructure one. Card
  transfers are approved by hand; a backlog means paying customers are waiting.

Both API colours are scraped, each labelled with its colour. Scraping only the
active one would blind the dashboard during the minute after a deploy - the minute
that matters most.

---

## 6. Backup and restore

```bash
make backup         # pg_dump -Fc, verified, AES-256 encrypted, retention applied
make restore-check  # validate the newest archive, change nothing
make restore        # DESTRUCTIVE, takes a safety dump first
```

Design decisions:

- **Custom format** (`-Fc`), so a single table can be restored selectively -
  usually what an incident actually needs.
- **Verified** by `pg_restore --list` and a table count before the dump is kept.
  `pg_dump` exiting 0 does not prove the output is readable.
- **Encrypted** before it can be copied off-site. The database contains Telegram
  ids, purchase histories and encrypted card data; an unencrypted dump in a
  misconfigured bucket is the most likely way this data ever leaks.
- **Retention applied only after a successful new backup**, so a failing job can
  never delete the last good copy.
- **A success timestamp** is written for node-exporter's textfile collector, which
  is what `BackupMissing` reads.
- **Restore takes a safety dump of the current database first**, and refuses to run
  without `--yes`.

**A backup that has never been test-restored is not a backup.** `restore-check`
proves the archive is readable, not that the data is usable. Rehearse a real
restore into a scratch database quarterly.

---

## 7. TLS

TLS 1.2 and 1.3, restricted to forward-secret AEAD suites. **1.2 is kept
deliberately**: a meaningful share of this product's users are on older Android
devices, and dropping 1.2 would lock them out to satisfy a scanner.

HSTS is set to two years with `includeSubDomains` but **is not preloaded**.
Preloading is effectively irreversible and would apply to every subdomain of the
domain forever, including ones not yet created.

Certificates renew twice daily via certbot with `--deploy-hook`. An unknown `Host`
header receives `421 Misdirected Request` from a `default_server` block rather than
being served the API, so scanners hitting the bare IP learn nothing.

---

## 8. Known gaps

Honest list; none of these are hidden elsewhere.

1. **Nothing was executed against real Docker, nginx, Prometheus or Grafana in the
   environment where it was written.** These files are validated by YAML parsing,
   `bash -n`, and the consistency gates - not by running them. The first real
   `docker compose up` will surface things no static check can.
2. **No automated smoke test of the monitoring stack.** The gate proves alert rules
   reference real metrics; nothing proves Alertmanager can actually reach Telegram.
   Send a test alert manually after the first deploy.
3. **Backups are host cron, not orchestrated.** Deliberate, and documented in
   section 2.5, but it means a rebuilt host silently loses its schedule until the
   36-hour alert fires.
4. **Single host.** There is no database replication and no failover. Recovery from
   host loss means provisioning a new host and restoring a backup: tens of minutes,
   not seconds.
5. **`/health/ready` treats Redis as required**, which converts a cache outage into
   an outage at the edge. Defensible, arguable, and called out in the runbook.
6. **Log aggregation is absent.** Logs are structured JSON but are only readable
   per-container with `docker logs`. Metrics tell you something is wrong; finding
   out why still means SSH.
