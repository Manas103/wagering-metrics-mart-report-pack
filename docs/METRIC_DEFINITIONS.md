# Metric definitions

One definition per metric, computed in exactly one place
(`wagering_mart/mart.py`, `MART_SQL`). Nothing downstream (the Excel pack,
the Streamlit dashboard, the README tables) recomputes a metric a second
way; everything reads the same `mart_metrics` table.

Grain: every metric below is computed at `(year_month, state, product)`
grain unless stated otherwise. `state` is a 2-letter simulated US state
code, `product` is one of the 12 catalog products (11 sports/casino
products plus `Same Game Parlay`, see "Product catalog" below).

## Data model

- **Bet leg**: one selection within a bet slip. A straight bet has exactly
  1 leg; a parlay has 2 to 6 legs, all tied together (all must win for the
  parlay to win). Table: `fact_bet_legs`, grain = one row per leg.
- **Settlement**: the outcome and payout of one bet (wager), at bet grain,
  not leg grain, because a customer is paid once per bet regardless of how
  many legs it has. Table: `fact_settlements`, grain = one row per bet.
- **Odds**: stored as both decimal odds (`decimal_odds`, the multiplier
  applied to stake on a win) and American odds (`american_odds`, the
  conventional +/- format US sportsbooks display). Decimal is what the
  math is actually done in; American is derived from it for display,
  using the standard conversion (`decimal >= 2` -> `(decimal-1)*100`,
  `decimal < 2` -> `-100/(decimal-1)`).
- **Currency**: every row is `USD`. The `currency` column exists because a
  real multi-state book's ledger carries it explicitly, and because a
  wrong-currency row is one of the 30 seeded defects (`mismatched_currency`).

## Handle

**Definition**: total dollars wagered, summed from the `stake` column of
`fact_settlements`, for a slice. Never summed from `fact_bet_legs`, because
a leg row does not carry its own independent stake, a parlay's stake is
one amount shared by all its legs; summing stake at leg grain would
overcount a 4-leg parlay's handle by 4x.

```sql
handle = SUM(stake)  -- from fact_settlements, grouped by slice
```

## Payout

Total dollars paid out to winners (or refunded on push/void), summed from
`fact_settlements.payout` for a slice.

## Net revenue

```
net_revenue = handle - payout
```

## Hold (actual / realized)

The fraction of handle the book actually kept, after real outcomes:

```
actual_hold = (handle - payout) / handle = net_revenue / handle
```

This is what a real sportsbook P&L reports; it varies session to session
because it depends on which side of each bet actually won, i.e. variance,
not just on the odds offered.

## Structural hold

The theoretical hold implied by the offered odds, computed from the odds
alone, before any bet settles, independent of which side wins. For a
single leg offered at decimal odds `d` against a modeled true win
probability `p_true` (the probability the selection actually wins, a
generator-internal quantity used to build a realistic odds line, not a
public number a real book would disclose):

```
leg_structural_hold = 1 - p_true * d
```

This is the standard "vig" formula: if the book offered fair (no-vig)
odds, `d` would equal `1 / p_true` and structural hold would be exactly 0;
every basis point of `d` below fair odds is edge kept by the book,
independent of outcome. For a parlay, legs combine multiplicatively
(independence assumed, a documented simplification, see Limitations):

```
parlay_decimal_odds = PRODUCT(leg decimal_odds)
parlay_true_prob     = PRODUCT(leg true_win_prob)
bet_structural_hold   = 1 - parlay_true_prob * parlay_decimal_odds
```

Computed in `generate.py` at generation time from the odds and modeled
true probabilities directly, stored per bet in `fact_settlements.structural_hold`,
never derived from `bet_outcome` or `payout`.

At slice grain, structural hold is the handle-weighted mean of the
per-bet structural hold, because a $1,000 bet's edge should count more
toward the slice's structural hold than a $5 bet's:

```sql
structural_hold = SUM(stake * structural_hold) / SUM(stake)
```

## Parlay mix

Parlay handle (not bet count, a deliberate choice, see below) as a
fraction of total handle, for a slice:

```sql
parlay_handle = SUM(CASE WHEN is_parlay THEN stake ELSE 0 END)
parlay_mix    = parlay_handle / handle
```

Handle, not bet count, was chosen because parlay stakes in this
simulation skew smaller than straight-bet stakes (a realistic pattern,
long-shot bettors risk less per parlay ticket), so a bet-count-based mix
would overstate parlay's economic weight relative to what the book
actually holds against.

**Known simplification, disclosed**: in this simulation, `product` fully
determines `is_parlay` (every `Same Game Parlay` row is a parlay, every
other product row is straight), so `parlay_mix` is only non-degenerate
when sliced by state or by month; sliced down to a single product row it
trivially reads 100% for `Same Game Parlay` and 0% for everything else.
That degeneracy is itself informative (it is exactly how much of total
handle sits in the parlay product line versus straight lines), but a
production mart would also carry cross-sport parlays tagged under their
constituent sports, which this generator does not model. See Limitations.

## Revenue per monthly unique payer (MUP)

Net revenue in a month, divided by the count of distinct customers who
placed at least one bet in that slice that month:

```sql
unique_payers   = COUNT(DISTINCT customer_id)  -- within the slice and month
revenue_per_mup = net_revenue / unique_payers
```

## Product catalog

11 straight-bet products (`NFL`, `NBA`, `MLB`, `NHL`, `NCAAF`, `NCAAB`,
`Soccer`, `Tennis`, `MMA`, `Golf`, `Casino`) plus `Same Game Parlay`, which
every parlay bet is tagged with regardless of which sports its legs draw
from. 12 products total, 13 simulated states, see `wagering_mart/config.py`
for the fixed lists and relative volume weights.

## Freshness / completeness gate

For the report month, every `(state, product)` partition that is expected
to exist (the full 13 x 12 = 156-combination universe) must be present in
the batch, and its `MAX(placed_ts)` must be within 24 hours of the run's
as-of time (default: the batch's own max `placed_ts`, i.e. "how stale is
the most recent partition relative to the most recent data anywhere in
the batch"). Either condition failing for any partition refuses the
entire publish. See `wagering_mart/freshness.py`.

## The 30 seeded defects

See `wagering_mart/quality_gate.py` (`RULES`, one function per defect id)
and `wagering_mart/defects.py` (`seed_defects`, which seeds exactly one
instance of each). The 30 ids: `negative_handle`, `negative_payout`,
`orphaned_settlement`, `duplicate_bet_id`, `missing_state`,
`missing_product`, `invalid_state_code`, `invalid_product`,
`settlement_before_placed`, `stale_partition`, `missing_partition`,
`mismatched_currency`, `zero_stake`, `odds_below_min`,
`implied_prob_over_100`, `parlay_single_leg`, `straight_multi_leg`,
`future_dated_bet`, `null_customer_id`, `duplicate_leg_id`,
`invalid_settlement_outcome`, `payout_exceeds_theoretical_max`,
`leg_missing_odds`, `bet_missing_settlement`,
`void_with_nonzero_delta_payout`, `zero_american_odds`,
`state_case_mismatch`, `customer_id_out_of_range`, `leg_count_mismatch`,
`timestamp_outside_report_window`.
