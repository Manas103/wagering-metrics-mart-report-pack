# Sales-pipeline metric definitions

One definition per metric, computed in exactly one place
(`sales_pipeline_mart/mart.py`, `MART_SQL`). Nothing downstream (the
Tableau extract, the Excel pack, the AI commentary checker, the README
tables) recomputes a metric a second way; everything reads the same
`mart_metrics` table.

Grain: every metric below is computed at `(year_month, region, product,
segment)` grain. `region` is one of 4 simulated regions (NA, EMEA, APAC,
LATAM), `product` is one of 6 simulated ad products, `segment` is one of
3 simulated account-size segments (Enterprise, Mid-Market, SMB).

## Data model

- **Pipeline event**: one row per (opportunity, day) that opportunity was
  open, logging which of the 4 stages (Prospecting, Qualification,
  Proposal, Negotiation) it was in that day. Table: `fact_pipeline_events`,
  grain = one row per opportunity per open day. This is the daily
  snapshot log a real pipeline-analytics feed would keep; it is also what
  the stage-regression check and the freshness gate both run against.
- **Bookings event**: the single close outcome (won or lost) of one
  opportunity. Table: `fact_bookings_events`, grain = one row per closed
  opportunity. An opportunity still open as of the report window's end has
  pipeline events but no bookings event yet (it has not closed), which is
  normal, not a defect; see `orphaned_pipeline_event` in `quality_gate.py`
  for how the gate tells that apart from an actual missing record.

## Bookings

**Definition**: total dollars from opportunities that closed won, summed
from `fact_bookings_events.amount` for a slice, grouped by the month the
opportunity closed.

```sql
bookings = SUM(amount) WHERE won  -- from fact_bookings_events, grouped by slice and close month
```

## Win rate

```sql
win_rate = won_count / (won_count + lost_count)  -- closed opportunities only, same slice and month
```

Opportunities still open are excluded entirely; win rate is never computed
over a denominator that includes undecided deals.

## Cycle time

**Definition**: average number of days between an opportunity's creation
and its close, for opportunities that closed in that slice and month.

```sql
cycle_time_days = AVG(cycle_days)  -- fact_bookings_events, grouped by slice and close month
```

Includes both won and lost deals: a sales cycle's length is a fact about
how long the opportunity was worked, not about whether it was won.

## Seller productivity

```sql
seller_productivity = bookings / COUNT(DISTINCT rep_id)  -- reps active in that slice and month
```

`active_reps` counts distinct reps who closed at least one opportunity
(won or lost) in that slice and month; a rep who only has open pipeline
that month, with nothing closed, is not counted as active for this metric.

## Open pipeline

**Definition**: total dollar amount of opportunities with at least one
pipeline event in that slice and month, counted once per opportunity
(`DISTINCT opp_id`) even though an open opportunity logs one event per
day it was open that month.

```sql
open_pipeline = SUM(amount)  -- DISTINCT opp_id per (year_month, region, product, segment), from fact_pipeline_events
```

## Coverage ratio

**Definition**: that slice's open pipeline divided by its own trailing
average bookings over the 1-3 months immediately before the current one
(a window of `ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING` on `bookings`,
ordered by month, within the same region/product/segment). This is a
planning heuristic ("how many multiples of recent run-rate bookings does
this slice have in open pipeline right now"), not a fitted model, and it
is undefined (`NULL`) for a slice's first 1-3 months, when there is no
preceding bookings history to average.

```sql
coverage_ratio = open_pipeline / AVG(bookings) OVER (
    PARTITION BY region, product, segment ORDER BY year_month
    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
)
```

## Report window and truncation

The simulated batch spans `REPORT_WINDOW_START` to
`REPORT_WINDOW_END_EXCLUSIVE` (`sales_pipeline_mart/config.py`). Both
fact tables are truncated at the window's end: an opportunity whose close
date would otherwise fall on or after that date is still open as of this
snapshot, so it appears only in `fact_pipeline_events` (up to the window
boundary), never in `fact_bookings_events`. This is what the `README`'s
Findings section calls out as the fix for an earlier version that let
these opportunities' close dates spill past the window and get flagged as
"future-dated," when they were really just still open.
