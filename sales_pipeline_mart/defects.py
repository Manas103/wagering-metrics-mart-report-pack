"""Builds a small, purpose-built fixture with exactly one seeded instance of
each of the 30 named defects in quality_gate.RULES, plus a ground-truth
ledger, so the gate's recall against a known-bad batch is a countable
fact. Mirrors wagering_mart/defects.py's approach: a small fixture (a few
thousand opportunities, not the real multi-million-event batch) so the
defect test runs in under a second, with every seeded defect kept clear of
every other one by hand-picking rows.
"""
from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

from . import config, generate

FIXTURE_N_OPPORTUNITIES = 1200


def _base_frames(seed: int = 11):
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={min(4, config.MAX_THREADS)}")
    old_seed = config.RNG_SEED
    try:
        config.RNG_SEED = seed
        stats = generate.generate(con, n_opportunities=FIXTURE_N_OPPORTUNITIES)
    finally:
        config.RNG_SEED = old_seed
    pipeline = con.execute("SELECT * FROM fact_pipeline_events").df()
    bookings = con.execute("SELECT * FROM fact_bookings_events").df()
    con.close()
    return pipeline, bookings, stats


def seed_defects(seed: int = 11):
    """Returns (pipeline_df, bookings_df, ledger_df, ctx) with 30 defects
    seeded, one per catalog id."""
    pipeline, bookings, stats = _base_frames(seed)
    pipeline = pipeline.reset_index(drop=True)
    bookings = bookings.reset_index(drop=True).sort_values("opp_id").reset_index(drop=True)

    as_of = pd.Timestamp(datetime.fromisoformat(config.REPORT_WINDOW_END_EXCLUSIVE))
    report_window = (
        pd.Timestamp(datetime.fromisoformat(config.REPORT_WINDOW_START)),
        pd.Timestamp(datetime.fromisoformat(config.REPORT_WINDOW_END_EXCLUSIVE)),
    )
    expected_partitions = set(
        map(tuple, pipeline[["region", "product", "segment"]].drop_duplicates().values)
    )
    ctx = {
        "as_of": as_of,
        "report_window": report_window,
        "expected_partitions": expected_partitions,
        "max_staleness_days": config.FRESHNESS_MAX_STALENESS_DAYS,
    }

    ledger = []

    def log(defect_id, table, key_val, desc):
        ledger.append({"defect_id": defect_id, "table": table, "key": key_val, "description": desc})

    n_book = len(bookings)
    b_idx = iter(range(0, n_book - 1))

    def next_b():
        return next(b_idx)

    # 1. negative_amount
    i = next_b()
    bookings.loc[i, "amount"] = -500.0
    log("negative_amount", "bookings", bookings.loc[i, "opp_id"], "amount < 0")

    # 2. zero_amount
    i = next_b()
    bookings.loc[i, "amount"] = 0.0
    log("zero_amount", "bookings", bookings.loc[i, "opp_id"], "amount == 0")

    # 3. missing_region
    i = next_b()
    bookings.loc[i, "region"] = None
    log("missing_region", "bookings", bookings.loc[i, "opp_id"], "region is null")

    # 4. missing_product
    i = next_b()
    bookings.loc[i, "product"] = None
    log("missing_product", "bookings", bookings.loc[i, "opp_id"], "product is null")

    # 5. missing_segment
    i = next_b()
    bookings.loc[i, "segment"] = None
    log("missing_segment", "bookings", bookings.loc[i, "opp_id"], "segment is null")

    # 6. invalid_region
    i = next_b()
    bookings.loc[i, "region"] = "ZZZZ"
    log("invalid_region", "bookings", bookings.loc[i, "opp_id"], "region not in simulated region universe")

    # 7. invalid_product_name
    i = next_b()
    bookings.loc[i, "product"] = "Carrier Pigeon Ads"
    log("invalid_product_name", "bookings", bookings.loc[i, "opp_id"], "product not in product catalog")

    # 8. invalid_segment
    i = next_b()
    bookings.loc[i, "segment"] = "Micro"
    log("invalid_segment", "bookings", bookings.loc[i, "opp_id"], "segment not in segment catalog")

    # 9. region_case_mismatch
    i = next_b()
    bookings.loc[i, "region"] = str(bookings.loc[i, "region"]).lower()
    log("region_case_mismatch", "bookings", bookings.loc[i, "opp_id"], "region valid but wrong case")

    # 10. close_before_created
    i = next_b()
    bookings.loc[i, "close_date"] = bookings.loc[i, "created_date"] - pd.Timedelta(days=5)
    log("close_before_created", "bookings", bookings.loc[i, "opp_id"], "close_date < created_date")

    # 11. negative_cycle_days
    i = next_b()
    bookings.loc[i, "cycle_days"] = -3
    log("negative_cycle_days", "bookings", bookings.loc[i, "opp_id"], "cycle_days < 0")

    # 12. zero_cycle_days
    i = next_b()
    bookings.loc[i, "cycle_days"] = 0
    log("zero_cycle_days", "bookings", bookings.loc[i, "opp_id"], "cycle_days == 0")

    # 13. duplicate_opp_id
    i = next_b()
    dup_row = bookings.iloc[[i]].copy()
    bookings = pd.concat([bookings, dup_row], ignore_index=True)
    log("duplicate_opp_id", "bookings", bookings.loc[i, "opp_id"], "opp_id appears twice in bookings")

    # 14. null_rep_id
    i = next_b()
    bookings.loc[i, "rep_id"] = None
    log("null_rep_id", "bookings", bookings.loc[i, "opp_id"], "rep_id is null")

    # 15. rep_id_out_of_range
    i = next_b()
    bookings.loc[i, "rep_id"] = config.N_REPS + 5000
    log("rep_id_out_of_range", "bookings", bookings.loc[i, "opp_id"], "rep_id outside the simulated rep pool")

    # 16. invalid_won_flag
    i = next_b()
    bookings["won"] = bookings["won"].astype(object)
    bookings.loc[i, "won"] = "maybe"
    log("invalid_won_flag", "bookings", bookings.loc[i, "opp_id"], "won not a boolean")

    # 17. future_dated_close
    i = next_b()
    bookings.loc[i, "close_date"] = as_of + pd.Timedelta(days=30)
    log("future_dated_close", "bookings", bookings.loc[i, "opp_id"], "close_date after as-of time")

    # 18. timestamp_outside_report_window
    i = next_b()
    bookings.loc[i, "close_date"] = report_window[0] - pd.Timedelta(days=200)
    log("timestamp_outside_report_window", "bookings", bookings.loc[i, "opp_id"], "close_date outside the claimed report window")

    # 19. opp_missing_pipeline_events: a bookings row with no matching
    # pipeline events at all.
    orphan_opp_id = int(pipeline["opp_id"].max()) + 999_999
    orphan_row = bookings.iloc[[0]].copy()
    orphan_row["opp_id"] = orphan_opp_id
    bookings = pd.concat([bookings, orphan_row], ignore_index=True)
    log("opp_missing_pipeline_events", "bookings", orphan_opp_id, "opp_id has no matching pipeline_events rows")

    # 20. amount_mismatch_vs_pipeline
    i = next_b()
    victim_opp = bookings.loc[i, "opp_id"]
    bookings.loc[i, "amount"] = float(bookings.loc[i, "amount"]) + 9999.0
    log("amount_mismatch_vs_pipeline", "bookings", victim_opp, "bookings amount disagrees with pipeline_events amount for same opp_id")

    # ---- pipeline-event-level defects ----
    n_pipe = len(pipeline)
    p_idx = iter(range(0, n_pipe - 1))

    def next_p():
        return next(p_idx)

    j = next_p()
    pipeline.loc[j, "stage"] = 9
    log("invalid_stage", "pipeline", pipeline.loc[j, "opp_id"], "stage not in {1,2,3,4}")

    j = next_p()
    pipeline.loc[j, "amount"] = -100.0
    log("negative_amount_pipeline", "pipeline", pipeline.loc[j, "opp_id"], "amount < 0 in a pipeline event row")

    j = next_p()
    dup_event = pipeline.iloc[[j]].copy()
    pipeline = pd.concat([pipeline, dup_event], ignore_index=True)
    log("duplicate_event", "pipeline", pipeline.loc[j, "opp_id"], "(opp_id, event_date) appears twice")

    # 24. orphaned_pipeline_event: a pipeline opp_id with no bookings row at all.
    orphan_pipeline_opp = int(bookings["opp_id"].max()) + 999_998
    orphan_pipeline_row = pipeline.iloc[[0]].copy()
    orphan_pipeline_row["opp_id"] = orphan_pipeline_opp
    pipeline = pd.concat([pipeline, orphan_pipeline_row], ignore_index=True)
    log("orphaned_pipeline_event", "pipeline", orphan_pipeline_opp, "opp_id has no matching bookings row")

    j = next_p()
    pipeline.loc[j, "stage"] = None
    log("missing_stage", "pipeline", pipeline.loc[j, "opp_id"], "stage is null")

    j = next_p()
    pipeline.loc[j, "event_date"] = report_window[0] - pd.Timedelta(days=500)
    log("event_date_outside_window", "pipeline", pipeline.loc[j, "opp_id"], "event_date outside the claimed report window")

    j = next_p()
    pipeline.loc[j, "region"] = "ZZZZ"
    log("region_mismatch_vs_bookings", "pipeline", pipeline.loc[j, "opp_id"], "pipeline event region disagrees with bookings region for same opp_id")

    # 28. missing_partition: drop one whole (region, product, segment) partition.
    miss_region, miss_product, miss_segment = sorted(expected_partitions)[0]
    keep_mask = ~(
        (pipeline["region"] == miss_region) & (pipeline["product"] == miss_product) & (pipeline["segment"] == miss_segment)
    )
    pipeline = pipeline.loc[keep_mask].reset_index(drop=True)
    log("missing_partition", "pipeline", f"{miss_region}|{miss_product}|{miss_segment}", "partition entirely absent from the batch")

    # 29. stale_partition: push one whole partition's max event_date far
    # outside the freshness window.
    stale_region, stale_product, stale_segment = sorted(expected_partitions)[1]
    stale_mask = (
        (pipeline["region"] == stale_region) & (pipeline["product"] == stale_product) & (pipeline["segment"] == stale_segment)
    )
    pipeline.loc[stale_mask, "event_date"] = report_window[0] - pd.Timedelta(days=10)
    log("stale_partition", "pipeline", f"{stale_region}|{stale_product}|{stale_segment}", "partition max event_date older than freshness threshold")

    # 30. stage_regression: flip one opportunity's chronologically last event
    # back to stage 1. Picked from the high end of the opp_id range (every
    # other pipeline-level defect above drew from the low end via next_p()),
    # and excluded from the dropped/stale partitions below, so this is the
    # only mutation ever applied to this opportunity's rows.
    bad_partitions = {
        (miss_region, miss_product, miss_segment),
        (stale_region, stale_product, stale_segment),
    }
    candidate_opps = pipeline.loc[
        ~pipeline[["region", "product", "segment"]].apply(tuple, axis=1).isin(bad_partitions),
        "opp_id",
    ]
    multi_event_opps = candidate_opps.value_counts()
    regression_opp = multi_event_opps[multi_event_opps >= 3].index.max()
    opp_rows = pipeline.loc[pipeline["opp_id"] == regression_opp].sort_values("event_date")
    last_row_index = opp_rows.index[-1]
    pipeline.loc[last_row_index, "stage"] = 1
    log("stage_regression", "pipeline", regression_opp, "a later event's stage is lower than an earlier event's stage")

    ledger_df = pd.DataFrame(ledger)
    assert ledger_df["defect_id"].nunique() == 30, (
        f"expected 30 distinct seeded defects, seeded {ledger_df['defect_id'].nunique()}"
    )
    return pipeline, bookings, ledger_df, ctx
