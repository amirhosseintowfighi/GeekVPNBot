# Analytics

Analytics answers two different questions with two different screens. The
operator dashboard answers *what needs me now* and is a queue of actions. The
analytics screen answers *how is the business doing* and is a set of trends
with comparisons and no verbs. They are kept apart deliberately: a screen that
is urgent about everything is urgent about nothing.

Everything is computed in `domain/analytics/`, which is pure arithmetic over
numbers that somebody else already collected -- no repository, no clock, no
I/O. That is what lets the admin panel, the CSV export and any future Telegram
digest quote the same figure for "net revenue" instead of three.

## Layout

| Package | Holds |
| --- | --- |
| `domain/analytics/` | Metric definitions, formulas, Jalali bucketing, segment and badge rules |
| `application/analytics/` | Ports, services, bundle assembly, CSV export |

No persistence layer is included. The readers in `application/analytics/ports.py`
are `Protocol`s that an infrastructure adapter must satisfy with SQL aggregates.

## Money and units

- Money is a plain `int` of whole Toman. The `Money` value object is not used
  here: analytics sums thousands of rows per request, allocating a value object
  per row buys nothing, and the payments context has already enforced the
  invariants those objects exist to protect.
- Traffic is GiB as `float`. `MIB_PER_GIB = 1024`; `gib_from_mib()` converts.
- Percentages are `float` in the range 0-100, never 0-1. Mixing the two
  conventions is the single most common source of a dashboard that is off by a
  factor of a hundred.

## Metric definitions

The formulas are one-liners, and the reason they are written down is that
everyone agrees on the words and nobody agrees on the arithmetic.

| Metric | Formula | Notes |
| --- | --- | --- |
| Gross revenue | sum of invoiced amounts | Before discounts |
| Collected | `gross - discounts` | What customers actually paid |
| **Net revenue** | `collected - refunds` | What the business keeps. This is the headline. |
| AOV | `collected / orders` | Uses collected, not net: a refund weeks later did not change the size of the order |
| ARPU | `net / paying_users` | Over *paying* users, not over everyone who opened the bot |
| Discount rate | `discounts / gross` | |
| Refund rate | `refunds / collected` | |
| Conversion | provisioned / entered funnel | See below |
| Renewal rate | `renewed / expired` | |
| Churn rate | `churned / active_start` | |
| LTV | `ARPU x 100 / churn_rate` | Falls back to `ARPU x lifetime_months` when churn is zero, because dividing by zero would report infinite customer value |
| Traffic sold | metered GiB | Unlimited plans counted separately |

`MetricKey` carries its own unit (`MetricFormat`) and its own direction of
virtue. `lower_is_better()` is true for churn and refunds, which is why the
admin panel does not need to special-case them beyond the `invert` prop it
already passes for `churn`.

### Comparisons

Every `MetricCard` carries the previous period's value and computes its own
arrow. A number without a comparison is decoration.

- `percent_change()` returns `None` when the baseline is zero. Going from zero
  to anything is not infinite growth; it is a first data point, and the card
  renders an em dash.
- Movement below `FLAT_THRESHOLD_PERCENT` (1%) is reported as `FLAT`. Noise
  should not render as a green arrow.
- `is_improvement()` returns `None` when flat, otherwise combines direction with
  `lower_is_better()`.

## Time ranges and Jalali bucketing

`DateRange` is half-open: `start` inclusive, `end` exclusive. Half-open ranges
make adjacent periods tile exactly, so `range.previous()` cannot double-count
the boundary day.

- Presets are 7 / 30 / 90 / 365 days, matching the admin panel's range picker.
- `MAX_RANGE_DAYS = 1095` (three years) caps unbounded scans.
- `suggested_granularity()`: up to 31 days renders daily, up to 120 weekly,
  beyond that monthly. Nobody can read 365 bars.
- **Weeks start on Saturday** (`offset = (weekday - 5) % 7`). A week that starts
  on Monday is wrong for an Iranian business and silently shifts every weekly
  bucket.
- Bucket labels are Jalali: `\u06f1\u06f2 \u0645\u0631\u062f\u0627\u062f` for days, `\u0645\u0631\u062f\u0627\u062f \u06f1\u06f4\u06f0\u06f5` for months.

The converter in `calendar.py` is verified against three anchors:
`2026-03-21 -> 1405/1/1`, `2026-08-03 -> 1405/5/12`, `2026-03-20 -> 1404/12/29`.

Timestamps are stored and compared in UTC everywhere. Jalali exists only in
labels.

## Charts

`TimeSeries.build()` fills **every** bucket in the range, inserting `0.0` where
there is no data. A chart that silently omits empty days draws a smooth line
through an outage.

- `moving_average(window=7)`, `cumulative()`, `ratio_to(other)` for derived
  lines. `ratio_to` raises `SeriesMismatch` on a length mismatch rather than
  zipping two different periods together.
- `Breakdown.build()` keeps the top N (default 6) and folds the tail into
  \u0633\u0627\u06cc\u0631. A donut with thirty slices communicates nothing.
- Every object exposes `as_dict()` with camelCase keys, because these objects
  *are* the wire format for the admin panel's existing chart components.

## Funnel

Stages, in order: `STARTED`, `VIEWED_SHOP`, `SELECTED_PLAN`, `INVOICE_CREATED`,
`PROOF_SUBMITTED`, `PAYMENT_APPROVED`, `PROVISIONED`.

`Funnel.build()` forces counts to be monotonically non-increasing. A funnel
where a later stage exceeds an earlier one is a data bug, and rendering it
produces a chart that looks like the business is manufacturing customers.

- `step_rate` is conversion from the previous stage; `overall_rate` is from the
  top.
- `worst_leak()` returns the biggest drop, and `needs_attention()` is true past
  `LEAK_THRESHOLD_PERCENT` (40%).
- `payment_completion_rate()` is provisioned divided by approved. This is the
  one that matters operationally: a customer whose money was taken and whose
  service never appeared is a support ticket and a refund, not a statistic.

## Retention and cohorts

- `CHURN_GRACE_DAYS = 14`. Somebody who expired yesterday has not churned; they
  have not renewed *yet*. Counting them immediately makes churn look terrible
  every month-end.
- `AT_RISK_DAYS = 7` before expiry.
- `CohortTable.average_rate_at()` is weighted by cohort size, so a 3-person
  cohort with 100% retention does not outvote a 300-person cohort.

## Referral and campaigns

Both answer the same uncomfortable question: did this cost more than it brought
in? Both therefore carry their cost alongside their revenue and can report a
negative return.

- Referral cost is `rewards_paid + invitee_bonuses`. Omitting the invitee bonus
  understates the programme's cost by roughly half.
- `return_on_spend` and `return_on_discount()` are percentages. Below 100 the
  thing gave away more than it earned back.
- The leaderboard ranks by **revenue produced**, not invitations sent. Ranking
  on raw invites rewards spamming; ranking on revenue rewards inviting people
  who actually want the product.

## Traffic sold and node usage

Unlimited plans are counted as a separate integer, never folded into the GiB
total. Assigning them a notional cap makes "traffic sold" mean whatever that
fake number happens to be this month.

Node load thresholds: `WARN_LOAD_PERCENT = 75`, `CRITICAL_LOAD_PERCENT = 90`.
Offline nodes contribute **zero** capacity to the fleet total, so the fleet does
not appear to have room that does not exist.

## Customer segmentation

A segment is a rule evaluated against a `CustomerSnapshot`, never a stored list.
Stored lists rot: a win-back list built on Saturday still contains people who
renewed on Sunday, and mailing them a discount for something they already bought
is worse than saying nothing.

| Segment | Rule |
| --- | --- |
| `NEVER_PURCHASED` | zero orders |
| `EXPIRING_SOON` | active and `0 <= days_to_expiry <= 7` |
| `EXPIRED` | inactive, within the 14-day grace period |
| `CHURNED` | inactive, past the grace period |
| `NEW` | joined within 14 days |
| `DORMANT` | no order in 60 days |
| `WHALE` | lifetime spend >= 3,000,000 Toman (the gold loyalty threshold, so the two never disagree) |
| `LOYAL` | 3 or more orders |
| `REFERRER` | at least one converted referral |
| `ACTIVE` | has an active subscription |
| `AT_RISK` | everything else |

Two functions, on purpose:

- `classify()` returns exactly **one** primary segment, in the priority order
  above, because a customer can only be targeted by one campaign at a time
  without feeling harassed. An expiring whale shows as \u062f\u0631 \u0622\u0633\u062a\u0627\u0646\u0647\u0654 \u0627\u0646\u0642\u0636\u0627
  because that is the fact worth acting on today.
- `matches()` allows overlap, for targeting queries like "every whale" that
  should include the ones currently about to expire.

`SegmentationService.win_back_audience()` deduplicates across the four win-back
segments, so nobody receives the same offer twice because two rules matched.

This service is also the natural `AudienceResolver` for the Phase 10 broadcast
engine: rules instead of a hand-kept list.

## Marketing tools

`MarketingService.suggestions()` returns advice, never actions. Auto-firing
discount campaigns from a heuristic trains customers to wait for the next sale
instead of paying full price.

Suggestions are raised for: win-back and expiring audiences above
`MIN_AUDIENCE_FOR_CAMPAIGN` (20), the worst funnel leak past the 40% threshold,
campaigns returning less than `WEAK_CAMPAIGN_RETURN_PERCENT` (150%) on their
discount, and a referral programme running at a loss. Priority is derived from
money or people at stake, not from opinion.

## Gamification

Deliberately cosmetic. Points buy nothing and expire never: the moment a badge
becomes spendable it is money, and money belongs in the payments context with an
audit trail, not in a motivational widget.

Points: 10 per order, 1 per 100,000 Toman spent, 25 per converted referral, 15
per badge. Levels at 0 / 50 / 150 / 400 / 900, labelled \u062a\u0627\u0632\u0647\u200c\u06a9\u0627\u0631, \u0647\u0645\u0631\u0627\u0647,
\u062d\u0631\u0641\u0647\u200c\u0627\u06cc, \u0642\u0647\u0631\u0645\u0627\u0646, \u0627\u0641\u0633\u0627\u0646\u0647.

Badges: first purchase, three renewals, six months, one year, big spender
(5,000,000 Toman), referrer rookie, referrer pro (5 conversions), early adopter.

Everything is **recomputed from a snapshot on every read**. Nothing is stored,
so a refunded order silently corrects the total instead of leaving a phantom
badge behind forever. The leaderboard shows display names only -- a public
ranking that leaks who bought a VPN is a safety problem, not a feature.

## CSV export

Two decisions that look like superstition and are not:

1. The file starts with a UTF-8 BOM. Excel on Windows -- which is what the
   finance side actually uses -- reads a BOM-less UTF-8 CSV as windows-1256 and
   renders every Persian heading as mojibake.
2. Values are ASCII digits, headings are Persian. A spreadsheet cannot sum
   \u06f1\u06f2\u06f3.

The filename is ASCII (`geekvpn-analytics-30d.csv`); Persian in
`Content-Disposition` requires RFC 5987 and still breaks in older clients.

## Wiring

```python
readers = AnalyticsReaders(
    revenue=..., funnel=..., retention=..., referral=...,
    campaigns=..., nodes=..., customers=..., work_queue=...,
)
service = AnalyticsService(readers=readers, clock=clock)
bundle = service.bundle(days=30)          # -> AnalyticsBundle
payload = bundle.as_dict()                # -> the admin panel's wire format
csv_text = bundle_csv(bundle)
```

The previous period is fetched on every call, doubling the reads. It is worth
it; see "Comparisons".

## What is not built

- No infrastructure adapters. The readers are unimplemented `Protocol`s.
- No HTTP routes. `/api/admin/analytics` and the CSV export endpoint are
  specified in `admin/docs/api-contract.md` but not yet served.
- No caching. `ReportCache` is declared and unused; analytics is correct without
  it, just slower.
- Phase 11 shipped documentation instead of tests, as requested.
