# Incident runbook

Every alert in `docker/monitoring/prometheus/alerts.yml` carries a `runbook`
annotation pointing at a section of this file. The alert message an operator
receives on Telegram contains that link, so a missing section here means the
link goes nowhere at the worst possible moment. A gate in
`scripts/deploy_gate.py` checks that every alert has the annotation; the
correspondence between anchor and section is checked by the docs gate below.

## How to use this document

Each section follows the same shape:

1. **What fired** - the condition, in plain language.
2. **What the customer sees** - because the priority of a fix depends on this, not
   on the severity label.
3. **First checks** - commands to run, in order.
4. **Likely causes** - ordered by how often they are actually the cause.
5. **Resolution**.

Two rules apply everywhere:

- **Take a backup before any destructive action.** `make backup` takes about a
  minute and has ended more incidents than it has caused.
- **Rollback is cheap; deciding to roll back is expensive.** `make rollback`
  flips traffic to the previous colour in about a second. If you are more than
  ten minutes into an incident caused by a deploy, roll back first and
  investigate afterwards.

---

## Quick reference

```bash
make deploy-status      # which colour is serving
make rollback           # flip to the previous colour
make prod-logs          # edge + both API colours
make backup             # encrypted, verified dump
make restore-check      # validate the newest backup, change nothing
make verify-config      # alerts/scrape/upstream/env consistency
```

Monitoring is deliberately not published to the internet. Reach Grafana through
an SSH tunnel:

```bash
ssh -L 3000:localhost:3000 <host>   # then open http://localhost:3000/grafana/
```

---

## api-down

**What fired.** No API instance is reporting to Prometheus at all
(`sum(up{job="geekvpn-api"}) == 0`).

**What the customer sees.** Total outage. The bot stops answering, the Mini App
shows a network error, and nobody can pay.

**First checks.**

```bash
make deploy-status                  # is a colour running at all?
make prod-logs                      # last lines before it stopped
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

**Likely causes**, in the order they actually occur:

1. **A deploy that half-finished.** nginx is pointed at a colour that never became
   healthy. `make rollback` fixes this in a second.
2. **Postgres or Redis is down**, so `/health/ready` fails and both colours are
   removed from rotation. The API is running but refuses traffic - which is
   correct behaviour, and the real incident is one section down.
3. **The host ran out of memory** and the kernel killed uvicorn. Check
   `dmesg | tail -30` for `Out of memory`. `API_MEMORY_LIMIT` exists to make this
   kill one container rather than the database.
4. **A configuration error at start-up.** The production guardrails in
   `settings.py` deliberately refuse to boot with a weak or missing secret. The
   log line is explicit; this is a fast fix, not a mystery.

**Resolution.** If a deploy is in progress, roll back. Otherwise fix the
dependency and the API returns to rotation by itself - no restart is needed,
because readiness is re-evaluated on every probe.

---

## high-error-rate

**What fired.** More than 2% of responses are 5xx over five minutes.

**What the customer sees.** Intermittent failures. Usually worse than it looks:
users retry, so a 2% error rate produces far more than 2% complaints.

**First checks.**

```bash
make prod-logs | grep -i 'error\|exception' | tail -40
```

On the Grafana overview, the **slowest paths** panel identifies whether this is
one endpoint or everything. One endpoint is a code bug; everything is a
dependency.

**Likely causes.** A newly deployed bug on one route; Postgres connection pool
exhaustion (see [postgres-connections](#postgres-connections)); a panel provider
returning errors, which surfaces as 502 through our adapters.

**Resolution.** If it started at a deploy annotation on the dashboard, roll back.
The annotation exists precisely so this question takes five seconds.

---

## latency

**What fired.** p95 request duration above 500ms for ten minutes. This is the
same threshold as the k6 load test in `scripts/loadtest/k6.js`, so the alert and
the test cannot disagree about what "acceptable" means.

**What the customer sees.** The Mini App feels sluggish. Nobody reports it; they
just buy less.

**First checks.** The slowest-paths panel, then:

```bash
# Slow queries: log_min_duration_statement=1000 is enabled in production.
make prod-logs 2>&1 | grep 'duration:' | tail -20
```

**Likely causes.** A missing index after a schema change (migration 0004 added
22 of them for exactly the queries that matter); an analytics export running
against the write database instead of the reporting engine; a slow panel provider
inside the checkout path.

**Resolution.** Identify the endpoint first. Restarting the API here is the
classic mistake: it clears the symptom for ten minutes and destroys the evidence.

---

## saturation

**What fired.** In-flight requests are sustained near the worker count, meaning
requests are queueing before they are even handled.

**First checks.** The in-flight panel, and `UVICORN_WORKERS` in `.env`.

**Likely causes.** Too few workers for the traffic; or - far more often - workers
blocked on something slow, so adding workers only queues the same problem
further in. Check [latency](#latency) before scaling.

**Resolution.** If latency is normal and in-flight is high, this is genuine load:
raise `UVICORN_WORKERS` and redeploy. Keep `POSTGRES__POOL_SIZE x workers` below
`POSTGRES_MAX_CONNECTIONS`, or you will trade this alert for
[postgres-connections](#postgres-connections).

---

## payment-backlog

**What fired.** More than 20 payments have been awaiting manual review for over
30 minutes.

**What the customer sees.** They paid by card transfer and are waiting for their
subscription. This is the alert most directly tied to revenue and to trust, and
it is not an infrastructure problem at all.

**First checks.** Open the admin panel review queue. Compare against the payment
transitions panel: if approvals stopped entirely, no operator is working.

**Likely causes.** Nobody is on shift; a promotion produced more transfers than
usual; or approvals are failing with an error, in which case this appears in the
logs and in [provisioning-failure](#provisioning-failure) instead.

**Resolution.** Staff the queue. If approvals are erroring, that is the real
incident. Do not "fix" this by bulk-approving unverified transfers.

---

## provisioning-failure

**What fired.** Subscriptions are failing to be created on a panel after payment.

**What the customer sees.** **They paid and received nothing.** The worst failure
mode in the product, which is why it has a dedicated critical alert rather than
living inside the general error rate.

**First checks.**

```bash
make prod-logs | grep -i 'provision' | tail -40
```

The `panel` label on the metric names which provider is failing.

**Likely causes.** Panel credentials expired or were rotated; the panel host is
down; the panel changed its API shape; the node is at capacity.

**Resolution.** Fix or fail over the panel. Then reconcile: every affected order
is in `provisioning` or `failed` state with the payment already captured. These
must be retried or refunded individually - provisioning is idempotent by
`idempotency_key`, so a retry cannot double-create an account.

---

## panel-slow

**What fired.** p95 latency to a panel provider is high.

**What the customer sees.** Slow checkout, and eventually failed provisioning if
it degrades further.

**Likely causes.** The provider is under load, or the network path to it is poor -
both outside our control. This alert is a warning rather than critical because a
slow panel is survivable; a broken one is not.

**Resolution.** If sustained, move new provisioning to another node or panel.

---

## notifications

**What fired.** Notification deliveries are failing.

**What the customer sees.** Nothing - and that is the danger. Expiry reminders
drive renewals, so silent failure here appears weeks later as churn rather than as
an error page.

**First checks.** The `channel` and `outcome` labels distinguish Telegram from
in-app inbox failures.

**Likely causes.** The bot token was revoked; Telegram is rate-limiting us; users
have blocked the bot (this is normal at low rates and should not fire the alert).

**Resolution.** Verify the token first: a revoked token fails every delivery at
once, which is the usual shape of this alert.

---

## auth-spike

**What fired.** A surge of authentication failures.

**First checks.** The `kind` label separates password attempts from TOTP failures
from Telegram init-data rejections. A spike in admin password failures is an
attack; a spike in TOTP failures is more often a clock problem.

**Likely causes.** Credential stuffing against `/api/v1/admin/auth`; a broken
client sending stale tokens; server clock drift breaking TOTP validation.

**Resolution.** The `auth.admin_login` policy already locks out escalating
attempts (5 per 15 minutes per IP, then an exponential lockout up to an hour). If
the source is a single network, add it to a deny rule at the edge. If admin
logins are being attempted from unexpected addresses at all, set
`ADMIN_ALLOW_CIDRS` - the admin panel has no reason to be reachable from the whole
internet.

---

## limiter-silent

**What fired.** **Zero** rate-limit refusals in an hour, under real traffic.

This is an inverted alert and the most subtle one in the set. The sliding-window
limiter **fails open** when Redis is unreachable: it allows the request rather
than taking the site down over a cache outage. That is the right trade-off, but it
means a Redis outage silently disables every rate limit - and nothing else would
tell you. A permanent zero here is the signature of that state.

**First checks.**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis \
  redis-cli -a "$REDIS__PASSWORD" ping
make prod-logs | grep 'ratelimit.unavailable' | tail
```

The log event `ratelimit.unavailable` is emitted on exactly this path.

**Resolution.** Restore Redis. Until then, assume the application is unprotected
against brute force and abuse.

---

## disk

**What fired.** `predict_linear` projects the filesystem filling within four
hours.

**What the customer sees.** Nothing yet. When Postgres cannot write, everything
fails at once and the database may need manual recovery - which is why this is
critical while there is still headroom.

**First checks.**

```bash
df -h
du -sh backups/ && ls -lt backups/ | head
docker system df
```

**Likely causes**, in order: old encrypted backups (`BACKUP_RETENTION_DAYS`
controls this, and pruning happens only after a successful new backup); Docker
image layers from repeated deploys; Postgres logs, which are verbose in production
because `log_min_duration_statement` and `log_lock_waits` are on.

**Resolution.** `docker image prune -a` is usually enough and is safe: running
containers keep their images. **Never delete the newest backup to free space.**

---

## postgres-connections

**What fired.** Connection usage is approaching `POSTGRES_MAX_CONNECTIONS`.

**What the customer sees.** Errors under load, arriving suddenly rather than
gradually: the pool is fine until it is entirely exhausted.

**First checks.**

```sql
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
SELECT pid, now() - query_start AS age, left(query, 80)
  FROM pg_stat_activity WHERE state <> 'idle' ORDER BY age DESC LIMIT 10;
```

**Likely causes.** Two API colours running simultaneously during a deploy, each
with a full pool - this is expected and brief. Long-running analytics queries
holding connections. `idle in transaction` sessions, which are a code defect: a
request that opened a transaction and never committed.

**Resolution.** Terminate genuinely stuck sessions with
`pg_terminate_backend(pid)`. The reporting engine is deliberately capped at
`pool_size=2, max_overflow=2` so analytics can never starve the write path;
if exhaustion traces back to reporting, that cap has been bypassed.

---

## redis-down

**What fired.** Redis is unreachable.

**What the customer sees.** Degraded but working: caching and rate limiting are
cooperative, not required. `/health/ready` fails, so **both colours leave rotation
and the site is effectively down at the edge.** This is deliberate - see below.

**First checks.**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs redis | tail -30
```

**Likely causes.** Redis hit `maxmemory` with `noeviction` and started refusing
writes. This policy is chosen on purpose: silently evicting rate-limit counters
would disable throttling with no signal at all, and a rate limiter that quietly
stops counting is worse than one that fails loudly.

**Resolution.** Restart Redis, then raise `REDIS_MAXMEMORY` if it was genuinely
full. Note that `/health/ready` treating Redis as required is a defensible but
arguable choice: it converts a cache outage into an outage. It is documented here
rather than hidden, because someone will eventually want to change it.

---

## backup-missing

**What fired.** No successful backup in over 36 hours. The metric
`geekvpn_backup_last_success_timestamp_seconds` is written by `scripts/backup.sh`
into node-exporter's textfile directory after the dump has been verified.

**What the customer sees.** Nothing, until the day it matters.

**First checks.**

```bash
ls -lt backups/ | head
cat backups/metrics/backup.prom
make backup                    # run one by hand; it reports its own failure
```

**Likely causes.** The cron entry is missing (the compose stack does **not**
schedule backups - this is a host-level cron job and a documented manual step);
`BACKUP_PASSPHRASE` is unset, in which case the script refuses to run rather than
write an unencrypted dump; the disk is full; the off-site upload failed.

**Resolution.** Fix the cause and run `make backup`. Then run `make restore-check`
against the result. **A backup that has never been test-restored is not a backup.**
Schedule a real restore rehearsal into a scratch database quarterly; the dry run
verifies the archive is readable, not that the data is usable.
