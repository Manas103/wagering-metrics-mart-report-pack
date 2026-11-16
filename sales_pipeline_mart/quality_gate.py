"""The 30 named data-quality rules the publish gate runs before anything
is allowed to reach the mart, the Tableau extract or the Excel pack. Same
discipline as wagering_mart/quality_gate.py: each rule is a small,
independently testable function, and the defect catalog id is the same
string here, in defects.py (which seeds it) and tests/test_pipeline_defects.py
(which asserts 30/30), so a reviewer can grep one string across all three.

Runs against two pandas frames (pipeline events, bookings events); the
full-scale freshness and stage-regression checks are separate SQL-only
gates (freshness.py, stage_regression.py) because they need to run
cheaply against the real multi-million-row batch, not the small seeded
fixture these 30 rules are tested against.
"""
from __future__ import annotations

import pandas as pd

from . import config

VALID_REGIONS = set(config.REGIONS)
VALID_PRODUCTS = set(config.PRODUCTS)
VALID_SEGMENTS = set(config.SEGMENTS)
VALID_STAGES = set(config.STAGES.keys())


def _flag(df: pd.DataFrame, mask: pd.Series, key_col: str) -> list:
    return sorted(df.loc[mask, key_col].tolist(), key=str)


# ---------------------------------------------------------------------
# Bookings-level rules
# ---------------------------------------------------------------------

def negative_amount(pipeline, bookings, ctx):
    return _flag(bookings, bookings["amount"] < 0, "opp_id")


def zero_amount(pipeline, bookings, ctx):
    return _flag(bookings, bookings["amount"] == 0, "opp_id")


def missing_region(pipeline, bookings, ctx):
    return _flag(bookings, bookings["region"].isna(), "opp_id")


def missing_product(pipeline, bookings, ctx):
    return _flag(bookings, bookings["product"].isna(), "opp_id")


def missing_segment(pipeline, bookings, ctx):
    return _flag(bookings, bookings["segment"].isna(), "opp_id")


def invalid_region(pipeline, bookings, ctx):
    r = bookings["region"]
    mask = r.notna() & ~r.str.upper().isin({v.upper() for v in VALID_REGIONS})
    return _flag(bookings, mask, "opp_id")


def invalid_product_name(pipeline, bookings, ctx):
    p = bookings["product"]
    mask = p.notna() & ~p.isin(VALID_PRODUCTS)
    return _flag(bookings, mask, "opp_id")


def invalid_segment(pipeline, bookings, ctx):
    s = bookings["segment"]
    mask = s.notna() & ~s.isin(VALID_SEGMENTS)
    return _flag(bookings, mask, "opp_id")


def region_case_mismatch(pipeline, bookings, ctx):
    r = bookings["region"]
    valid_upper = {v.upper() for v in VALID_REGIONS}
    mask = r.notna() & r.str.upper().isin(valid_upper) & (r != r.str.upper())
    return _flag(bookings, mask, "opp_id")


def close_before_created(pipeline, bookings, ctx):
    return _flag(bookings, bookings["close_date"] < bookings["created_date"], "opp_id")


def negative_cycle_days(pipeline, bookings, ctx):
    return _flag(bookings, bookings["cycle_days"] < 0, "opp_id")


def zero_cycle_days(pipeline, bookings, ctx):
    return _flag(bookings, bookings["cycle_days"] == 0, "opp_id")


def duplicate_opp_id(pipeline, bookings, ctx):
    dupe = bookings["opp_id"][bookings["opp_id"].duplicated(keep=False)]
    return sorted(set(dupe.tolist()), key=str)


def null_rep_id(pipeline, bookings, ctx):
    return _flag(bookings, bookings["rep_id"].isna(), "opp_id")


def rep_id_out_of_range(pipeline, bookings, ctx):
    r = bookings["rep_id"]
    mask = r.notna() & ((r < 0) | (r >= config.N_REPS))
    return _flag(bookings, mask, "opp_id")


def invalid_won_flag(pipeline, bookings, ctx):
    mask = ~bookings["won"].isin([True, False])
    return _flag(bookings, mask, "opp_id")


def future_dated_close(pipeline, bookings, ctx):
    as_of = ctx["as_of"]
    return _flag(bookings, bookings["close_date"] > as_of, "opp_id")


def timestamp_outside_report_window(pipeline, bookings, ctx):
    start, end = ctx["report_window"]
    mask = (bookings["close_date"] < start) | (bookings["close_date"] >= end)
    return _flag(bookings, mask, "opp_id")


def opp_missing_pipeline_events(pipeline, bookings, ctx):
    pipeline_opps = set(pipeline["opp_id"].unique())
    booked_opps = set(bookings["opp_id"].unique())
    return sorted(booked_opps - pipeline_opps, key=str)


def amount_mismatch_vs_pipeline(pipeline, bookings, ctx):
    pipeline_amount = pipeline.groupby("opp_id")["amount"].first().rename("pipeline_amount")
    merged = bookings.merge(pipeline_amount, on="opp_id", how="left")
    mask = (merged["amount"] - merged["pipeline_amount"]).abs() > 0.01
    mask = mask & merged["pipeline_amount"].notna()
    return sorted(merged.loc[mask, "opp_id"].tolist(), key=str)


# ---------------------------------------------------------------------
# Pipeline-event-level rules
# ---------------------------------------------------------------------

def invalid_stage(pipeline, bookings, ctx):
    mask = ~pipeline["stage"].isin(VALID_STAGES)
    return _flag(pipeline, mask, "opp_id")


def negative_amount_pipeline(pipeline, bookings, ctx):
    return _flag(pipeline, pipeline["amount"] < 0, "opp_id")


def duplicate_event(pipeline, bookings, ctx):
    dupe_mask = pipeline.duplicated(subset=["opp_id", "event_date"], keep=False)
    return sorted(set(pipeline.loc[dupe_mask, "opp_id"].tolist()), key=str)


def orphaned_pipeline_event(pipeline, bookings, ctx):
    """A pipeline opp_id with no matching bookings row is only a defect if
    its event log stopped well before the report window's end: an
    opportunity still genuinely open as of the snapshot always has its
    last event within a couple of days of the window end, by construction
    (the daily log runs until it closes or the window ends, whichever is
    first), so a pipeline opp_id whose last event is much older than that
    and still has no bookings row did not simply fail to close yet, it is
    missing a record it should have."""
    booked_opps = set(bookings["opp_id"].unique())
    last_event = pipeline.groupby("opp_id")["event_date"].max()
    window_end = ctx["report_window"][1]
    stale_cutoff = pd.Timestamp(window_end) - pd.Timedelta(days=3)
    orphan_mask = (~last_event.index.isin(booked_opps)) & (last_event < stale_cutoff)
    return sorted(last_event.index[orphan_mask].tolist(), key=str)


def missing_stage(pipeline, bookings, ctx):
    return _flag(pipeline, pipeline["stage"].isna(), "opp_id")


def event_date_outside_window(pipeline, bookings, ctx):
    start, end = ctx["report_window"]
    mask = (pipeline["event_date"] < start) | (pipeline["event_date"] >= end)
    return sorted(set(pipeline.loc[mask, "opp_id"].tolist()), key=str)


def region_mismatch_vs_bookings(pipeline, bookings, ctx):
    booking_region = bookings.set_index("opp_id")["region"]
    merged = pipeline.merge(booking_region.rename("booking_region"), on="opp_id", how="left")
    mask = merged["booking_region"].notna() & (merged["region"] != merged["booking_region"])
    return sorted(set(merged.loc[mask, "opp_id"].tolist()), key=str)


# ---------------------------------------------------------------------
# Partition-level rules (batch, not row grain)
# ---------------------------------------------------------------------

def missing_partition(pipeline, bookings, ctx):
    expected = ctx.get("expected_partitions") or set()
    present = set(map(tuple, pipeline[["region", "product", "segment"]].dropna().drop_duplicates().values))
    return sorted(expected - present)


def stale_partition(pipeline, bookings, ctx):
    as_of = ctx["as_of"]
    max_staleness = ctx.get("max_staleness_days", config.FRESHNESS_MAX_STALENESS_DAYS)
    g = pipeline.dropna(subset=["region", "product", "segment"]).groupby(["region", "product", "segment"])["event_date"].max()
    stale = g[(pd.Timestamp(as_of) - pd.to_datetime(g)).dt.days > max_staleness]
    return sorted(stale.index.tolist())


def stage_regression(pipeline, bookings, ctx):
    ordered = pipeline.sort_values(["opp_id", "event_date"])
    prev_stage = ordered.groupby("opp_id")["stage"].shift(1)
    mask = prev_stage.notna() & (ordered["stage"] < prev_stage)
    return sorted(set(ordered.loc[mask, "opp_id"].tolist()), key=str)


RULES = {
    "negative_amount": negative_amount,
    "zero_amount": zero_amount,
    "missing_region": missing_region,
    "missing_product": missing_product,
    "missing_segment": missing_segment,
    "invalid_region": invalid_region,
    "invalid_product_name": invalid_product_name,
    "invalid_segment": invalid_segment,
    "region_case_mismatch": region_case_mismatch,
    "close_before_created": close_before_created,
    "negative_cycle_days": negative_cycle_days,
    "zero_cycle_days": zero_cycle_days,
    "duplicate_opp_id": duplicate_opp_id,
    "null_rep_id": null_rep_id,
    "rep_id_out_of_range": rep_id_out_of_range,
    "invalid_won_flag": invalid_won_flag,
    "future_dated_close": future_dated_close,
    "timestamp_outside_report_window": timestamp_outside_report_window,
    "opp_missing_pipeline_events": opp_missing_pipeline_events,
    "amount_mismatch_vs_pipeline": amount_mismatch_vs_pipeline,
    "invalid_stage": invalid_stage,
    "negative_amount_pipeline": negative_amount_pipeline,
    "duplicate_event": duplicate_event,
    "orphaned_pipeline_event": orphaned_pipeline_event,
    "missing_stage": missing_stage,
    "event_date_outside_window": event_date_outside_window,
    "region_mismatch_vs_bookings": region_mismatch_vs_bookings,
    "missing_partition": missing_partition,
    "stale_partition": stale_partition,
    "stage_regression": stage_regression,
}

assert len(RULES) == 30, f"expected 30 quality rules, found {len(RULES)}"


def run_gate(pipeline: pd.DataFrame, bookings: pd.DataFrame, ctx: dict) -> dict:
    """Run all 30 rules. Returns {defect_id: [flagged keys]}."""
    return {defect_id: fn(pipeline, bookings, ctx) for defect_id, fn in RULES.items()}


def gate_passed(results: dict) -> bool:
    return all(len(v) == 0 for v in results.values())
