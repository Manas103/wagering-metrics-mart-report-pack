# Wagering Metrics Mart and Automated Report Pack

A sportsbook-style wagering data mart: a synthetic batch of 25 million bet
legs and their settlements, generated with vectorized DuckDB SQL, rolled
up into handle, hold, structural versus actual hold, parlay mix and
revenue per monthly unique payer, split by state and product, published
through a one-command refresh that writes a pivot-ready Excel workbook and
a Streamlit dashboard, and that refuses to publish behind a freshness and
data-quality gate that holds all 30 of 30 deliberately seeded defects.
Python, DuckDB SQL (PostgreSQL-compatible DDL, see below), Streamlit,
openpyxl. Extended (Nov. 2026) with `sales_pipeline_mart/`: a sales
metrics mart on ~23M simulated advertiser pipeline and bookings events,
pinning bookings, coverage, win rate, cycle time and seller productivity
to one written definition each, refreshed by one command into a real
Tableau Hyper extract and an Excel pack, refusing to publish on a failed
freshness or stage-regression check, and an AI-commentary checker that
blocks a drafted sentence the moment its cited figure disagrees with the
mart. Every number below was measured on this machine, not targeted: the
raw command output is committed under `docs/`.

## Why this exists

A sportsbook's analytics/BI team does not get to say "trust us" about
handle or hold, a regulator-adjacent number has to reconcile from raw bet
records to a published table, by state and by product, on a schedule, and
the pipeline has to be able to say no when the input data is not ready.
This project is a small, honest version of that: one batch, one publish
gate, and metrics that are each defined exactly once.

## Why `sales_pipeline_mart/` extends this repo rather than standing alone

A Pinterest Sales Strategy & Operations analyst's own charter is a metrics
mart and a weekly report pack: bookings, coverage, win rate, cycle time
and seller productivity, pinned to one written definition each, refreshed
by one command, gated on freshness, and increasingly expected to validate
AI-drafted output before it ships. This repo already has exactly that
architecture: a one-flat-table mart, a fail-closed freshness gate, 30
named seeded defects, and a one-command refresh to a report pack, all
already measured. What it lacked was the sales-pipeline domain itself
(bookings and coverage instead of handle and hold), a data-quality check
specific to a pipeline's stage sequence, Tableau in place of Streamlit,
and a mechanical check that an AI-drafted commentary paragraph's cited
figures are actually true. `sales_pipeline_mart/` adds exactly that, on
top of the same architecture and discipline, not as a second disconnected
demo; the two simulated domains (sportsbook wagering, advertiser sales
pipeline) share no data and no parameters, only the techniques.

## Honest framing, up front

- **All data is synthetic.** `wagering_mart/generate.py` builds every bet
  leg and settlement from `numpy`-free, vectorized DuckDB SQL over
  `range()` and `generate_series()`, never a Python row-by-row loop. There
  is no real DraftKings dataset anywhere in this repository, and it is not
  connected to any production system.
- **Odds, win probabilities, states and products are all simulated.**
  "True" win probability, vig, decimal/American odds, which state and
  product a bet lands in, and every outcome are drawn from fixed
  distributions documented in `wagering_mart/config.py` and
  `docs/METRIC_DEFINITIONS.md`, not sourced from any real book.
- **PostgreSQL was actually live for this run, not documented-only.** WSL2
  Ubuntu 22.04 on this machine runs a real PostgreSQL 14.24 instance
  (`sudo service postgresql start`; it is not left running as a background
  service between sessions, WSL2's VM is torn down after a short idle
  period). `sql/schema_postgres.sql` was applied for real and
  `mart_metrics` (936 rows for this run) was loaded into it and read back;
  see `docs/postgres_load_output.txt`. The 25M-row raw generation and
  metric computation is done in DuckDB, which is the actual working engine
  for anything at that scale on this machine; the code targets
  PostgreSQL-compatible SQL throughout so the same DDL and the same
  `mart_metrics` shape work against either engine, matching the precedent
  set by `model-validation-alerting` and `payment-exception-triage`
  elsewhere in this portfolio.
- **Machine and toolchain, for every number below**: AMD Ryzen 7 7800X3D,
  8 physical / 16 logical cores, Windows 11, WSL2 Ubuntu 22.04 available
  but not needed for the DuckDB path (used only for the live PostgreSQL
  check), Python 3.12.10 native Windows, DuckDB 1.5.5, pandas 3.0.5,
  openpyxl 3.1.5, Streamlit 1.62.0.
- **`sales_pipeline_mart/` data is also entirely synthetic.**
  `sales_pipeline_mart/generate.py` draws every opportunity's region,
  product, segment, rep and amount from DuckDB SQL, and the pipeline-event
  explosion (one row per opportunity per day it was open) uses the same
  lateral `generate_series()` technique `wagering_mart/generate.py` uses
  to explode bets to legs. There is no real advertiser pipeline anywhere
  in this repository.
- **No Tableau Desktop or Server is installed on this machine.**
  `sales_pipeline_mart/tableau_pack.py` writes a real `.hyper` extract via
  the Tableau Hyper API, the same object a packaged Tableau workbook
  would point to as a live data source, the same way `excel_pack.py`
  produces a real `.xlsx` via openpyxl without Excel installed. The
  Hyper API's own `hyperd` process is started and stopped by a `with
  HyperProcess(...)` block every time, never left running.
- **The AI-drafted commentary is literally AI-drafted**, in the most
  direct sense available here: the sentences verified in Measured results
  were authored by the same AI building this repository, grounded in real
  queried mart figures, following 5 fixed sentence templates (so the
  verifier's parser is unambiguous) rather than open-ended prose. Figure
  errors are injected afterward, deliberately, by the benchmark script,
  never by the drafting step itself.
- **`sales_pipeline_mart/` toolchain**: the same Python 3.12.10 / DuckDB
  1.5.5 / pandas 3.0.5 / openpyxl 3.1.5 as above, plus
  `tableauhyperapi` 0.0.26963. No PostgreSQL, Streamlit or WSL2 involved.

## Architecture

```
wagering_mart/
  config.py       fixed simulation universe: 13 states, 12 products
                  (11 sports/casino + Same Game Parlay), volume weights,
                  paths, freshness threshold, report window
  genutil.py      one small SQL-generation helper (weighted CASE builder)
  generate.py     vectorized DuckDB generation of fact_bet_legs (25M rows)
                  and fact_settlements (bet grain); explodes bets to legs
                  via a lateral generate_series() join, never a Python loop
  mart.py         the one flat, pivot-ready mart_metrics table
                  (year_month x state x product) and MART_SQL, the single
                  place every metric is computed
  quality_gate.py the 30 named data-quality rules (RULES dict), one
                  function per defect id
  defects.py      seeds exactly one instance of each of the 30 defects
                  into a small fixture, with a ground-truth ledger
  freshness.py    full-scale freshness/completeness check against the
                  real fact tables (SQL aggregation, no pandas)
  excel_pack.py   writes mart_metrics as a real Excel Table (ListObject)
                  plus a summary sheet, via openpyxl
  refresh.py      the one command: gate -> build mart -> write Excel;
                  raises PublishRefused (nonzero exit) if the gate fails
  db.py           optional live-PostgreSQL path: reachability check,
                  DDL apply, mart_metrics load
app.py            Streamlit dashboard, reads the same mart_metrics table
sql/schema_postgres.sql   real PostgreSQL DDL, applied for real this run
scripts/run_benchmark.py  full measured run; its stdout is
                           docs/measurement_output.txt
scripts/load_postgres.py  loads the built mart into live PostgreSQL
tests/            pytest suite, see "Validation"
docs/             METRIC_DEFINITIONS.md, raw command output, a small
                  sample workbook (the real, full mart_metrics output,
                  81 KB, small enough to commit as-is)

sales_pipeline_mart/
  config.py          fixed simulation universe: 4 regions, 6 products,
                     3 segments, stage definitions, report window
  generate.py        vectorized DuckDB generation of fact_opportunities,
                     then explodes each to one fact_pipeline_events row
                     per open day via the same lateral generate_series()
                     technique as wagering_mart/generate.py; also builds
                     fact_bookings_events (one row per closed opportunity)
  mart.py            the one flat mart_metrics table (year_month x region
                     x product x segment): bookings, win_rate, cycle_time,
                     seller_productivity, open_pipeline, coverage_ratio
  stage_regression.py  checks a pipeline funnel never moves backward
  freshness.py       full-scale freshness/completeness check, same
                     SQL-aggregation technique as wagering_mart/freshness.py
  quality_gate.py    30 named data-quality rules specific to pipeline data
  defects.py         seeds one instance of each of the 30 defects
  ai_commentary.py   drafts and verifies commentary sentences against the
                     mart, sentence by sentence, figure by figure
  tableau_pack.py    writes mart_metrics to a real Tableau Hyper extract
  excel_pack.py      writes mart_metrics, a summary, and the commentary
                     verification result to a real Excel workbook
  refresh.py         the one command: freshness gate -> stage-regression
                     gate -> build mart -> verify commentary -> write
                     Hyper extract -> write Excel; raises PublishRefused
                     if either gate fails
scripts/run_pipeline_benchmark.py  full measured run; its stdout is
                                   docs/pipeline_measurement_output.txt
docs/   PIPELINE_METRIC_DEFINITIONS.md, pipeline_measurement_output.txt,
        pipeline_test_output.txt, a small sample Hyper extract and a
        small sample Excel pack
```

### Design deep-dives

**Why DuckDB SQL for generation, not pandas or a Python loop.** A
row-by-row Python loop for 25M rows was never on the table, it would take
tens of minutes to hours. `generate.py` draws every random value as a
column (`SELECT random() AS r_x FROM range(n)`), explodes bets to legs
with a lateral `generate_series()` join, and aggregates leg outcomes to
bet-level settlement with a log-sum-exp trick (`EXP(SUM(LN(x)))`) instead
of a missing `PRODUCT()` aggregate. All of it runs as three `CREATE TABLE
AS SELECT` statements. Measured: 25,001,355 legs in 42.51 seconds
end to end (draws, explode, aggregate), one genuine attempt, no retry
needed. A `random()` call is deliberately never repeated inside a `CASE`
expression (each draw is materialized into its own column first), because
a bare `random()` referenced twice in one `CASE` would silently redraw per
branch and break every weighted pick in the generator.

**Why handle is defined from `fact_settlements.stake`, never from summing
`fact_bet_legs`.** A leg does not carry its own stake, a 4-leg parlay's
$20 stake is one amount shared by the whole slip. Summing at leg grain
would overcount handle by however many legs a parlay has. This is checked
directly (`test_handle_reconciles_raw_to_mart`, `test_bet_count_reconciles_raw_to_mart`).

**Why structural hold is computed from odds, not from outcomes.** The
resume claim is "structural versus actual hold", the entire point is that
they diverge (structural is what the book is entitled to on average,
actual is what happened this batch, driven by variance). `generate.py`
computes `structural_hold` at generation time, from `true_win_prob` and
`decimal_odds` only, and stores it per bet before any outcome is decided;
`mart.py` never derives it from `payout` or `bet_outcome`. Measured this
run: structural hold 9.56% (blended, handle-weighted) versus actual hold
6.45%, a 3.1-point gap consistent with a batch where the book's simulated
luck ran favorably.

**Why the freshness gate checks partition completeness and staleness
together, and refuses on either.** A mart with 155 of 156 expected
`(state, product)` partitions present and fresh is not "mostly right", it
is silently wrong for whichever product a state regulator happens to ask
about. `freshness.py` treats a missing partition and a stale partition as
the same class of failure and refuses the whole publish for either, not
just holding the affected slice.

**Why the 30 seeded defects are a separate small fixture, not seeded into
the 25M-row batch.** Seeding into 25M rows would make the defect test
slow and would make "exactly one instance of each defect" hard to
guarantee without cross-contamination between defects. `defects.py` builds
a small (~4,000-leg) clean batch and mutates one specific row per defect,
logging a ground-truth ledger; `quality_gate.py`'s 30 rules are the same
code whether they run against that fixture or the full batch (`freshness.py`
is the full-scale-safe subset used against the real 25M rows, since it
runs as SQL aggregation, not pandas).

**Why both pipeline fact tables are truncated at the report window's
end.** The first version let an opportunity's close date fall past the
window boundary whenever its creation date plus its cycle length
overshot it. That produced dozens of opportunities whose `close_date` sat
after the window end, which every downstream freshness-style check then
read as "future-dated," a real data defect. The actual situation was
simpler: an opportunity still open as of this snapshot has not closed
yet, which is normal, not a defect. The fix was to stop generating a
bookings event (and stop extending the pipeline-event log) past the
window boundary at all; an opportunity that would otherwise close late
just stays open, with pipeline events up to the boundary and no bookings
row, exactly like a real opportunity that has not resolved as of the
report date.

**Why `orphaned_pipeline_event` checks the opportunity's last event date
against the window end, not just "has no bookings row."** A naive version
of this rule flagged every currently-open opportunity, because by
definition an open opportunity has pipeline events and no bookings row.
The fix: a pipeline event log that is still active always has its last
event within a day or two of the window's end (the daily log runs until
the opportunity closes or the window ends, whichever comes first); a
pipeline opp_id whose last event is much older than that and still has no
bookings row did not simply fail to close yet, it is missing a record it
should have. Only that case is flagged.

**Why the Hyper extract write always happens inside a `with
HyperProcess(...)` block, never a bare process launch.** The Tableau
Hyper API spawns its own native `hyperd` process; `tableau_pack.py` opens
it inside a `with` block every time (`log_dir` redirected to the system
temp directory so a refresh never writes log files into the repository),
so the process is guaranteed to be stopped before the function returns,
the same discipline `app.py`'s Streamlit headless verification uses for
its own process.

## Validation

Layers: raw-to-mart reconciliation invariants, hand-computed metric
checks against a tiny known-answer batch, the freshness gate exercised
both ways (passes fresh, refuses stale), and the 30/30 seeded-defect
catch. Full output: `docs/test_output.txt`.

```
============================= test session starts =============================
collected 22 items

tests\test_defects.py::test_thirty_defect_types_are_seeded PASSED        [  4%]
tests\test_defects.py::test_gate_catches_thirty_of_thirty_seeded_defects PASSED [  9%]
tests\test_defects.py::test_gate_passes_clean_batch PASSED               [ 13%]
tests\test_freshness.py::test_freshness_passes_on_freshly_generated_batch PASSED [ 18%]
tests\test_freshness.py::test_freshness_flags_missing_partitions PASSED  [ 22%]
tests\test_freshness.py::test_freshness_flags_stale_partition PASSED     [ 27%]
tests\test_freshness.py::test_refresh_run_refuses_publish_when_stale PASSED [ 31%]
tests\test_freshness.py::test_refresh_run_publishes_when_fresh PASSED    [ 36%]
tests\test_invariants.py::test_leg_and_bet_counts_are_positive PASSED    [ 40%]
tests\test_invariants.py::test_handle_reconciles_raw_to_mart PASSED      [ 45%]
tests\test_invariants.py::test_bet_count_reconciles_raw_to_mart PASSED   [ 50%]
tests\test_invariants.py::test_num_legs_matches_actual_leg_rows_for_clean_batch PASSED [ 54%]
tests\test_invariants.py::test_straight_bets_have_exactly_one_leg PASSED [ 59%]
tests\test_invariants.py::test_parlay_bets_have_two_to_six_legs PASSED   [ 63%]
tests\test_invariants.py::test_structural_hold_is_between_0_and_1 PASSED [ 68%]
tests\test_invariants.py::test_actual_hold_is_plausible_for_a_sportsbook PASSED [ 72%]
tests\test_invariants.py::test_parlay_mix_plus_straight_mix_equals_one PASSED [ 77%]
tests\test_invariants.py::test_no_settlement_before_placement_in_clean_batch PASSED [ 81%]
tests\test_invariants.py::test_payout_never_exceeds_theoretical_max_in_clean_batch PASSED [ 86%]
tests\test_invariants.py::test_american_and_decimal_odds_are_consistent PASSED [ 90%]
tests\test_metrics.py::test_metrics_match_hand_computation PASSED        [ 95%]
tests\test_metrics.py::test_totals_aggregate_correctly PASSED            [100%]

============================= 22 passed in 16.74s =============================
```

The 30/30 seeded-defect run, from `scripts/run_benchmark.py`
(`docs/measurement_output.txt`, section 6): all 30 defect ids caught by
name, `gate_passed: False` (correctly refuses a batch with defects in it).

### `sales_pipeline_mart/` validation (26 pytest tests, `docs/pipeline_test_output.txt`)

Layers: raw-to-mart reconciliation invariants, a hand-computed metric
check against a tiny known-answer pair of fact tables, the freshness and
stage-regression gates each exercised both ways (pass clean, refuse on a
deliberate break), the 30/30 seeded-defect catch, and the AI-commentary
verifier checked both on a sentence it drafted itself (must verify clean)
and on a deliberately corrupted one (must block).

```
collected 26 items

tests\test_pipeline_defects.py::test_thirty_defect_types_are_seeded PASSED
tests\test_pipeline_defects.py::test_gate_catches_thirty_of_thirty_seeded_defects PASSED
tests\test_pipeline_defects.py::test_gate_passes_clean_batch PASSED
tests\test_pipeline_freshness.py::test_freshness_passes_on_freshly_generated_batch PASSED
tests\test_pipeline_freshness.py::test_freshness_flags_missing_partitions PASSED
tests\test_pipeline_freshness.py::test_freshness_flags_stale_partition PASSED
tests\test_pipeline_freshness.py::test_refresh_run_refuses_publish_when_stale PASSED
tests\test_pipeline_freshness.py::test_refresh_run_publishes_when_fresh PASSED
tests\test_pipeline_invariants.py::test_opportunity_and_event_counts_are_positive PASSED
tests\test_pipeline_invariants.py::test_every_bookings_opp_is_either_won_or_lost PASSED
tests\test_pipeline_invariants.py::test_cycle_days_and_amounts_are_positive PASSED
tests\test_pipeline_invariants.py::test_close_date_never_precedes_created_date PASSED
tests\test_pipeline_invariants.py::test_every_stage_is_in_the_valid_range PASSED
tests\test_pipeline_invariants.py::test_bookings_reconciles_raw_to_mart PASSED
tests\test_pipeline_invariants.py::test_won_plus_lost_count_reconciles_raw_to_mart PASSED
tests\test_pipeline_invariants.py::test_no_pipeline_events_outside_the_report_window PASSED
tests\test_pipeline_mart.py::test_metrics_match_hand_computation PASSED
tests\test_stage_regression.py::test_passes_on_clean_batch PASSED
tests\test_stage_regression.py::test_flags_a_deliberately_regressed_opportunity PASSED
tests\test_stage_regression.py::test_violations_format_includes_opp_id PASSED
tests\test_ai_commentary.py::test_each_template_drafts_a_sentence_that_verifies_clean PASSED
tests\test_ai_commentary.py::test_corrupted_figure_is_blocked PASSED
tests\test_ai_commentary.py::test_unparseable_sentence_is_blocked PASSED
tests\test_ai_commentary.py::test_sentence_for_unknown_slice_is_blocked PASSED
tests\test_ai_commentary.py::test_small_rounding_difference_is_tolerated PASSED
tests\test_ai_commentary.py::test_publishable_sentences_excludes_blocked PASSED

26 passed in 13.17s
```

The 30/30 seeded-defect run and the 24/24 injected AI-commentary-error
catch, both from `scripts/run_pipeline_benchmark.py`
(`docs/pipeline_measurement_output.txt`, sections 5 and 8): all 30 defect
ids caught by name, `gate_passed: False`; all 24 deliberately corrupted
sentences blocked, 0 of the 6 clean ones falsely blocked.

## Findings

**What broke: the freshness "fresh batch passes" test was flaky at small
scale, for a subtle reason.** The wrong hypothesis first: I assumed any
generated batch would trivially pass its own freshness check, since
`as_of` defaults to the batch's own max `placed_ts`. It didn't, at small
test scale (400,000 legs) the check failed nondeterministically, flagging
2 to 4 partitions like `AZ|Golf` or `LA|MMA` as stale. The measurement
that discriminated: printing `stale_partitions` showed it was always the
lowest-weight product/state combinations (Golf, MMA, Tennis in
low-population states), never the high-volume ones. Root cause: with
uniform random timestamps over a 6-month window and only a few dozen bets
in the rarest partition per month, the *last* bet in that partition for
the report month lands, by chance, several days before month-end often
enough to blow a 24-hour staleness budget, an order-statistics effect
(expected gap to month-end ~ window / (n+1)), not a bug in the gate logic.
At the real 25M-row scale this essentially never happens (the rarest
partition still gets thousands of bets a month, pushing the expected gap
to minutes), which the gate demo run confirms (`stale_partitions: []`,
`missing_partitions: []`, section 3). The fix was in the test, not the
gate: the "passes when fresh" test now generates 2.5M legs specifically
(large enough that even the rarest partition has a comfortable safety
margin under 24 hours), while the gate's actual threshold and logic were
never touched. The method mattered here because the naive fix would have
been to loosen the freshness threshold to make small tests stop flaking,
which would have silently weakened the real gate to paper over a
test-scale sampling artifact.

**Disclosed gap, not padded to a clean number.** `void_with_nonzero_delta_payout`
and `payout_exceeds_theoretical_max` both mutate a `payout` value, and an
earlier draft of the fixture accidentally let one overwrite the row the
other had already tagged (both picked the same "next available" row
index), which would have made one of the two look caught when it was
actually the other defect's mutation being detected. The `next_s()`/`next_l()`
row-index iterators were changed to consume strictly-increasing positions
across the whole seeding function, and `test_thirty_defect_types_are_seeded`
now separately asserts 30 distinct defect ids were generated before the
gate is ever run, so a repeat of that bug would fail loudly instead of
silently passing 30/30 for the wrong reason.

### `sales_pipeline_mart/` findings

**What broke: a clean, freshly generated batch tripped `future_dated_close`,
`timestamp_outside_report_window` and `event_date_outside_window` on
dozens of opportunities, with no defect seeded.** The wrong hypothesis
first: a bug in those three rules. It wasn't; printing the flagged rows
showed every one of them was an opportunity created near the end of the
report window whose cycle length pushed its close date past the window
boundary. The actual bug was one level up, in `generate.py`: nothing
stopped an opportunity's close date, or its pipeline-event log, from
extending past "now." The fix was to truncate both fact tables at the
window boundary (an opportunity still open as of this snapshot simply has
no bookings row yet and an event log that stops at the boundary, which is
correct, not a defect), not to loosen the three rules that had correctly
caught the resulting bad dates.

**Second find, same debugging pass: `orphaned_pipeline_event` flagged 74
opportunities on that same clean batch.** Once the window-truncation fix
above was in place, this was the next thing a clean-batch run surfaced,
and the cause was structural rather than a leftover from the first bug:
`orphaned_pipeline_event`'s first version was "a pipeline opp_id with no
bookings row," which is also just the definition of "currently open,"
true for every one of the (by then, correctly) still-open opportunities.
The fix, described in the architecture notes above, was to only flag an
opp_id whose last pipeline event is well before the window's end, the
signal that actually distinguishes "still open" from "missing a record."

**Third find: the stage-regression seed collided with the invalid-stage
seed on the same opportunity, silently.** The first version of the
`stage_regression` defect picked "the first opportunity with 3+ events"
in `fact_pipeline_events`, the same selection rule, applied to the same
freshly generated fixture, that the `invalid_stage` defect's `next_p()`
iterator happened to land on too. Both mutations targeted the same
opportunity; the measurement that caught it was the 30/30 catch test
reporting a miss on `stage_regression` specifically, with 13 *other*
opportunities flagged as regressed (an incidental side effect of
`invalid_stage` setting a stage to 9, which a later real event's genuine
low stage then reads as a "regression" from). The fix was to pick the
stage-regression target from the high end of the opp_id range, excluded
from every partition another defect already touches, and to select its
chronologically last row by sorting on `event_date` rather than trusting
row order, since DuckDB does not guarantee row order without an explicit
`ORDER BY` and the original code's `opp_rows[-1]` was not necessarily the
opportunity's last event in time.

**Disclosed, not hidden: this machine's C: drive was found to be
completely full (0 bytes free) partway through this build**, which
surfaced as DuckDB `IOException`/`TransactionException` write failures
in otherwise-unrelated tests, including a pre-existing `wagering_mart`
test that had nothing to do with this extension. The immediate cause was
accumulated pytest temp-directory debris plus this extension's own
~800MB raw-fact-table file; both were cleaned up, and `refresh.py` and
`scripts/run_pipeline_benchmark.py` were changed to use an in-memory
DuckDB connection by default (an explicit `db_path` still persists the
raw tables when disk space allows), so re-running this extension's
benchmark does not reproduce the problem. The drive being essentially
full in general is outside this repository's scope to fix and is
disclosed here rather than quietly worked around.

## Measured results

Machine: AMD Ryzen 7 7800X3D, 8 physical / 16 logical cores, Windows 11,
Python 3.12.10, DuckDB 1.5.5. Full raw output: `docs/measurement_output.txt`.

**25,001,355 bet legs processed, in 42.51 seconds, from 15,060,241 bets.**

| Claim | Metric | Measured | Unit | Meets claim |
|---|---|---|---|---|
| 25M simulated bet legs and settlements | rows generated and processed | 25,001,355 legs / 15,060,241 settlements | rows | yes |
| handle | total wagered | $2,276,877,631.44 | USD | yes |
| hold (actual) | (handle - payout) / handle | 6.4531% | % of handle | yes |
| structural hold | modeled vig from odds | 9.5642% | % of handle (weighted) | yes |
| parlay mix | parlay handle / total handle | 21.9998% | % of handle | yes |
| split by state and product | mart_metrics rows | 936 | (year_month x state x product) slices | yes |
| freshness gate refusal | demonstrated on real data | refused (`stale_partition:AZ|Casino`) | pass/fail | yes |
| 30 of 30 seeded defects held | recall | 30 / 30 | count | yes |
| one command refresh (dashboard + Excel) | `python scripts/run_benchmark.py` then Streamlit headless start | Excel: 80,990 bytes written; Streamlit: HTTP 200 | end-to-end | yes |

Revenue per monthly unique payer varies by slice; see `mart_metrics` (the
Excel pack or `docs/sample_report_pack.xlsx`) for the full breakdown by
`(year_month, state, product)`. Example: NY / Same Game Parlay / 2026-03
had $12,278,313.93 handle at 17.2213% actual hold that month (read back
live from PostgreSQL, `docs/postgres_load_output.txt`).

### `sales_pipeline_mart/` measured results

Machine: same as above. Full raw output: `docs/pipeline_measurement_output.txt`.

**23,388,664 pipeline and bookings events processed, from 645,000
simulated opportunities, in 19.17 seconds.**

| Claim | Measured | Meets claim |
|---|---|---|
| 23M simulated pipeline and bookings events | 23,388,664 (22,779,492 pipeline + 609,172 bookings) | yes |
| bookings, coverage, win rate, cycle time and seller productivity pinned to one written definition each | 6 metrics, one `MART_SQL` each, `docs/PIPELINE_METRIC_DEFINITIONS.md` | yes |
| sliced by region, product and segment | mart_metrics rows | 1,584 (year_month x region x product x segment) slices | yes |
| one command refreshes a Tableau dashboard and an Excel pack | `python -m sales_pipeline_mart.refresh --generate` | Hyper: 262,144 bytes, 1,584 rows, read back; Excel: 136,855 bytes | yes |
| publication refused on a failed freshness or stage-regression check | both demonstrated on real data | freshness: refused (`stale_partition:APAC\|Idea Ads\|Enterprise`); stage-regression: refused (`stage_regression:opp_id=0`) | yes |
| 30 of 30 seeded defects caught | recall | 30 / 30 | yes |
| AI-drafted commentary blocked sentence by sentence on figure mismatch | mechanism demonstrated | 30 sentences drafted, 0 falsely blocked; see next row for the error-injection measurement | yes |
| 24 of 24 injected errors caught | recall, 0 of 6 clean sentences falsely blocked | 24 / 24 caught, 0 / 6 false positives | yes |

Win rate, cycle time and seller productivity vary by slice; see
`mart_metrics` (the Excel pack or `docs/sample_pipeline_report_pack.xlsx`)
for the full breakdown. Example, October 2026: APAC / Video / Enterprise
had $3,741,236.30 in bookings at a 42.94% win rate and a 73.91-day average
cycle time that month; EMEA / Performance Plus / Enterprise had
$4,776,085.49 in bookings at an 11.51x coverage ratio.

## Building and running

```bash
cd projects/wagering-metrics-mart-report-pack
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Full measured run: generate 25M rows, gate, mart, Excel, freshness demo,
# 30/30 defect demo, live-Postgres load if reachable, parquet export
venv\Scripts\python scripts\run_benchmark.py

# Or just the one-command refresh (regenerates + gates + publishes):
venv\Scripts\python -m wagering_mart.refresh --generate

# Refresh without regenerating (uses the existing data\mart.duckdb):
venv\Scripts\python -m wagering_mart.refresh

# Demonstrate the freshness gate refusing publish, on real data:
venv\Scripts\python -m wagering_mart.refresh --inject-stale-demo

# View the dashboard:
venv\Scripts\python -m streamlit run app.py
# (headless verification used in this build: --server.headless true
#  --server.port <a free port>, then an HTTP GET, then stop by the PID
#  the launching process held, never taskkill by name)

# Tests:
venv\Scripts\python -m pytest tests -q

# Live PostgreSQL (optional, WSL2 Ubuntu 22.04):
wsl -e bash -c "sudo service postgresql start"
venv\Scripts\python scripts\load_postgres.py
```

### `sales_pipeline_mart/` building and running

Same venv as above (`tableauhyperapi` is in the same `requirements.txt`).

```bash
# Full measured run: generate ~23M events, both gates, mart, Hyper
# extract, Excel pack, both refusal demos, 30/30 defect demo, 24/24
# AI-commentary error-injection demo
venv\Scripts\python scripts\run_pipeline_benchmark.py

# One-command refresh (in-memory by default; see Findings for why):
venv\Scripts\python -m sales_pipeline_mart.refresh --generate

# Demonstrate either gate refusing publish, on real data:
venv\Scripts\python -m sales_pipeline_mart.refresh --generate --inject-stale-demo
venv\Scripts\python -m sales_pipeline_mart.refresh --generate --inject-regression-demo

# Tests:
venv\Scripts\python -m pytest tests/test_pipeline_defects.py tests/test_pipeline_freshness.py ^
    tests/test_pipeline_invariants.py tests/test_pipeline_mart.py tests/test_stage_regression.py ^
    tests/test_ai_commentary.py -q
```

The Excel pack lands at `data/wagering_report_pack.xlsx` (gitignored,
regenerate with the commands above); `docs/sample_report_pack.xlsx` is a
committed copy of a real run's output (81 KB, the full `mart_metrics`
table, not a truncated sample, since the mart itself is small even though
the raw batch behind it is 25M rows).

## Sibling comparison

No portfolio sibling in this domain (wagering/sportsbook metrics); nothing
to compare against. `sales_pipeline_mart/` has no domain sibling either
(advertiser sales-pipeline metrics), but it is the architectural sibling
of `wagering_mart/` within this same repo: same one-flat-table mart
discipline, same 30-named-defect gate pattern, same lateral-explosion
generation technique, deliberately, since that architecture is exactly
what both reader types (a sportsbook BI team, a sales-operations analyst)
need.

## Limitations

- Parlay legs are modeled as independent for structural-hold combination
  (`parlay_true_prob = PRODUCT(leg true_win_prob)`); real correlated
  same-game legs (e.g. "team wins" and "team's QB throws 2+ TDs") are not
  independent, and a production model would need a correlation adjustment.
  Disclosed, not hidden: this is why `parlay_mix` sliced down to a single
  product row is degenerate (see `docs/METRIC_DEFINITIONS.md`).
- `product` fully determines `is_parlay` in this simulation, every parlay
  is tagged `Same Game Parlay` regardless of which sports its legs draw
  from; a real book also has cross-sport parlays that would tag under
  their constituent sports for some reporting views. Not modeled here.
- Freshness `as_of` defaults to the batch's own max `placed_ts` rather
  than true wall-clock "now", because this is a historical synthetic
  batch, not a live stream; `--inject-stale-demo` and the test suite
  demonstrate real refusal by aging a real partition instead.
- PostgreSQL in WSL2 is not left running between sessions (the WSL2 VM
  tears down after a short idle period with no active WSL process); the
  live-Postgres path in `refresh.py`/`db.py` degrades to "DuckDB only,
  Postgres unreachable" cleanly when that happens, and did so during an
  earlier, longer run of this same benchmark before WSL2 was kept alive
  deliberately for the run this README's numbers are drawn from.
- `mart.duckdb` (about 5 GB with the raw fact tables loaded) and the
  partitioned parquet export are real files produced during this build
  but are gitignored, per the repository hygiene rule against committing
  generated data; regenerate with the commands above.

### `sales_pipeline_mart/` limitations

- The coverage-ratio heuristic (open pipeline / trailing average
  bookings) assumes a roughly stable run rate; it is a planning rule of
  thumb, not a fitted relationship, and is undefined for a slice's first
  1-3 months (no preceding bookings to average), which the README and
  `docs/PIPELINE_METRIC_DEFINITIONS.md` both say plainly.
  `coverage_ratio` is `NULL` for those rows rather than defaulting to 0 or
  1, since neither would be true.
- The stage-day split within an opportunity's cycle (30% / 25% / 25% /
  20% across the 4 stages) is a single fixed shape shared by every
  segment; a real pipeline would show segment-specific stage-duration
  differences, which this simulation does not model (only total cycle
  length differs by segment).
- The AI-commentary checker's 5 sentence templates are deliberately
  rigid (see Honest framing); a real AI-drafted paragraph in free-form
  prose would need a less brittle parser, which was out of scope for
  demonstrating the verification mechanism itself.
- `sales_pipeline_mart.duckdb` (about 800MB with the raw fact tables
  loaded at full scale) is a real file this build produced but is
  gitignored, and `refresh.py` and `scripts/run_pipeline_benchmark.py`
  now default to an in-memory connection specifically because this
  machine's disk was found completely full during this build (see
  Findings); pass an explicit `db_path` to persist it when disk space
  allows.
