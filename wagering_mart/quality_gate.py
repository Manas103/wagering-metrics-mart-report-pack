"""The 30 named data-quality rules the publish gate runs before anything
is allowed to reach the mart or the report pack.

Each rule is a small, independently testable function over the two fact
frames (legs, settlements). `run_gate` runs all 30 plus the freshness rule
(see freshness.py, run separately at full 25M scale) and returns, per rule,
the exact keys it flagged, so recall against seeded ground truth is a
countable fact rather than an assertion.

Naming: the defect catalog id is the same string in defects.py (which
seeds it), here (which detects it) and tests/test_defects.py (which
asserts 30/30), on purpose, so a reviewer can grep one string across all
three files.
"""
from __future__ import annotations

import pandas as pd

from . import config

VALID_STATES = set(config.STATES)
VALID_PRODUCTS = set(config.PRODUCTS)
VALID_OUTCOMES = {"win", "loss", "push", "void"}
VALID_CURRENCY = config.CURRENCY


def _flag(df: pd.DataFrame, mask: pd.Series, key_col: str) -> list:
    return sorted(df.loc[mask, key_col].tolist(), key=str)


# ---------------------------------------------------------------------
# Settlement-level rules
# ---------------------------------------------------------------------

def negative_handle(legs, settlements, ctx):
    return _flag(settlements, settlements["stake"] < 0, "bet_id")


def zero_stake(legs, settlements, ctx):
    return _flag(settlements, settlements["stake"] == 0, "bet_id")


def negative_payout(legs, settlements, ctx):
    return _flag(settlements, settlements["payout"] < 0, "bet_id")


def missing_state(legs, settlements, ctx):
    return _flag(settlements, settlements["state"].isna(), "bet_id")


def missing_product(legs, settlements, ctx):
    return _flag(settlements, settlements["product"].isna(), "bet_id")


def invalid_state_code(legs, settlements, ctx):
    s = settlements["state"]
    mask = s.notna() & ~s.str.upper().isin(VALID_STATES)
    return _flag(settlements, mask, "bet_id")


def state_case_mismatch(legs, settlements, ctx):
    s = settlements["state"]
    mask = s.notna() & s.str.upper().isin(VALID_STATES) & (s != s.str.upper())
    return _flag(settlements, mask, "bet_id")


def invalid_product(legs, settlements, ctx):
    p = settlements["product"]
    mask = p.notna() & ~p.isin(VALID_PRODUCTS)
    return _flag(settlements, mask, "bet_id")


def mismatched_currency(legs, settlements, ctx):
    return _flag(settlements, settlements["currency"] != VALID_CURRENCY, "bet_id")


def settlement_before_placed(legs, settlements, ctx):
    return _flag(settlements, settlements["settled_ts"] < settlements["placed_ts"], "bet_id")


def duplicate_bet_id(legs, settlements, ctx):
    dupe_ids = settlements["bet_id"][settlements["bet_id"].duplicated(keep=False)]
    return sorted(set(dupe_ids.tolist()), key=str)


def null_customer_id(legs, settlements, ctx):
    return _flag(settlements, settlements["customer_id"].isna(), "bet_id")


def customer_id_out_of_range(legs, settlements, ctx):
    c = settlements["customer_id"]
    mask = c.notna() & ((c < 0) | (c >= config.N_CUSTOMERS))
    return _flag(settlements, mask, "bet_id")


def invalid_settlement_outcome(legs, settlements, ctx):
    mask = ~settlements["bet_outcome"].isin(VALID_OUTCOMES)
    return _flag(settlements, mask, "bet_id")


def void_with_nonzero_delta_payout(legs, settlements, ctx):
    v = settlements[settlements["bet_outcome"] == "void"]
    mask = (v["payout"] - v["stake"]).abs() > 0.01
    return sorted(v.loc[mask, "bet_id"].tolist(), key=str)


def payout_exceeds_theoretical_max(legs, settlements, ctx):
    # Theoretical max payout for a bet = stake * product of ALL legs' decimal
    # odds (the payout if every leg had won), a hard ceiling regardless of
    # what actually happened. Anything above it is impossible.
    max_mult = legs.groupby("bet_id")["decimal_odds"].apply(lambda s: s.prod())
    merged = settlements.merge(max_mult.rename("max_mult"), on="bet_id", how="left")
    mask = merged["payout"] > merged["stake"] * merged["max_mult"] * 1.0001 + 0.01
    return sorted(merged.loc[mask, "bet_id"].tolist(), key=str)


def future_dated_bet(legs, settlements, ctx):
    as_of = ctx["as_of"]
    return _flag(settlements, settlements["placed_ts"] > as_of, "bet_id")


def timestamp_outside_report_window(legs, settlements, ctx):
    start, end = ctx["report_window"]
    mask = (settlements["placed_ts"] < start) | (settlements["placed_ts"] >= end)
    return _flag(settlements, mask, "bet_id")


def parlay_single_leg(legs, settlements, ctx):
    mask = settlements["is_parlay"] & (settlements["num_legs"] <= 1)
    return _flag(settlements, mask, "bet_id")


def leg_count_mismatch(legs, settlements, ctx):
    actual = legs.groupby("bet_id").size().rename("actual_legs")
    merged = settlements.merge(actual, on="bet_id", how="left")
    merged["actual_legs"] = merged["actual_legs"].fillna(0)
    mask = merged["num_legs"] != merged["actual_legs"]
    return sorted(merged.loc[mask, "bet_id"].tolist(), key=str)


def bet_missing_settlement(legs, settlements, ctx):
    leg_bets = set(legs["bet_id"].unique())
    settled_bets = set(settlements["bet_id"].unique())
    return sorted(leg_bets - settled_bets, key=str)


# ---------------------------------------------------------------------
# Leg-level rules
# ---------------------------------------------------------------------

def orphaned_settlement(legs, settlements, ctx):
    leg_bets = set(legs["bet_id"].unique())
    mask = ~settlements["bet_id"].isin(leg_bets)
    return _flag(settlements, mask, "bet_id")


def duplicate_leg_id(legs, settlements, ctx):
    dupe = legs["leg_id"][legs["leg_id"].duplicated(keep=False)]
    return sorted(set(dupe.tolist()), key=str)


def odds_below_min(legs, settlements, ctx):
    return _flag(legs, legs["decimal_odds"] <= 1.0, "leg_id")


def implied_prob_over_100(legs, settlements, ctx):
    return _flag(legs, legs["implied_prob"] > 1.0, "leg_id")


def zero_american_odds(legs, settlements, ctx):
    return _flag(legs, legs["american_odds"] == 0, "leg_id")


def leg_missing_odds(legs, settlements, ctx):
    return _flag(legs, legs["american_odds"].isna(), "leg_id")


def straight_multi_leg(legs, settlements, ctx):
    actual = legs.groupby("bet_id").size().rename("actual_legs")
    merged = settlements.merge(actual, on="bet_id", how="left")
    merged["actual_legs"] = merged["actual_legs"].fillna(0)
    mask = (~merged["is_parlay"]) & (merged["actual_legs"] > 1)
    return sorted(merged.loc[mask, "bet_id"].tolist(), key=str)


# ---------------------------------------------------------------------
# Partition-level rules (batch, not row grain)
# ---------------------------------------------------------------------

def missing_partition(legs, settlements, ctx):
    expected = ctx.get("expected_partitions") or set()
    present = set(map(tuple, settlements[["state", "product"]].dropna().drop_duplicates().values))
    return sorted(expected - present)


def stale_partition(legs, settlements, ctx):
    as_of = ctx["as_of"]
    max_staleness = ctx.get("max_staleness_hours", config.FRESHNESS_MAX_STALENESS_HOURS)
    g = settlements.dropna(subset=["state", "product"]).groupby(["state", "product"])["placed_ts"].max()
    stale = g[(as_of - g).dt.total_seconds() > max_staleness * 3600]
    return sorted(stale.index.tolist())


RULES = {
    "negative_handle": negative_handle,
    "negative_payout": negative_payout,
    "orphaned_settlement": orphaned_settlement,
    "duplicate_bet_id": duplicate_bet_id,
    "missing_state": missing_state,
    "missing_product": missing_product,
    "invalid_state_code": invalid_state_code,
    "invalid_product": invalid_product,
    "settlement_before_placed": settlement_before_placed,
    "stale_partition": stale_partition,
    "missing_partition": missing_partition,
    "mismatched_currency": mismatched_currency,
    "zero_stake": zero_stake,
    "odds_below_min": odds_below_min,
    "implied_prob_over_100": implied_prob_over_100,
    "parlay_single_leg": parlay_single_leg,
    "straight_multi_leg": straight_multi_leg,
    "future_dated_bet": future_dated_bet,
    "null_customer_id": null_customer_id,
    "duplicate_leg_id": duplicate_leg_id,
    "invalid_settlement_outcome": invalid_settlement_outcome,
    "payout_exceeds_theoretical_max": payout_exceeds_theoretical_max,
    "leg_missing_odds": leg_missing_odds,
    "bet_missing_settlement": bet_missing_settlement,
    "void_with_nonzero_delta_payout": void_with_nonzero_delta_payout,
    "zero_american_odds": zero_american_odds,
    "state_case_mismatch": state_case_mismatch,
    "customer_id_out_of_range": customer_id_out_of_range,
    "leg_count_mismatch": leg_count_mismatch,
    "timestamp_outside_report_window": timestamp_outside_report_window,
}

assert len(RULES) == 30, f"expected 30 quality rules, found {len(RULES)}"


def run_gate(legs: pd.DataFrame, settlements: pd.DataFrame, ctx: dict) -> dict:
    """Run all 30 rules. Returns {defect_id: [flagged keys]}."""
    results = {}
    for defect_id, fn in RULES.items():
        results[defect_id] = fn(legs, settlements, ctx)
    return results


def gate_passed(results: dict) -> bool:
    return all(len(v) == 0 for v in results.values())
