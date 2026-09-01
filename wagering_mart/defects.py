"""Builds a small, purpose-built fixture with exactly one seeded instance of
each of the 30 named defects in quality_gate.RULES, plus a ground-truth
ledger, so the gate's recall against a known-bad batch is a countable fact.

This fixture is intentionally separate from the 25M-row measurement batch:
it needs to be small (a few thousand rows) so the defect test runs in
under a second, and it needs every seeded defect to be uncontaminated by
the others, which is easiest to guarantee by hand-picking rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
import numpy as np
import pandas as pd

from . import config, generate

FIXTURE_TARGET_LEGS = 4000


def _base_frames(seed: int = 7):
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={min(4, config.MAX_THREADS)}")
    np.random.seed(seed)
    stats = generate.generate(con, target_legs=FIXTURE_TARGET_LEGS)
    legs = con.execute("SELECT * FROM fact_bet_legs").df()
    settlements = con.execute("SELECT * FROM fact_settlements").df()
    con.close()
    return legs, settlements, stats


def seed_defects(seed: int = 7):
    """Returns (legs_df, settlements_df, ledger_df, ctx) with 30 defects
    seeded, one per catalog id, and ctx carrying the freshness/window
    parameters the gate needs (as_of, report_window, expected_partitions)."""
    legs, settlements, stats = _base_frames(seed)
    legs = legs.reset_index(drop=True)
    settlements = settlements.reset_index(drop=True).sort_values("bet_id").reset_index(drop=True)

    as_of = pd.Timestamp(datetime.fromisoformat(config.REPORT_WINDOW_END_EXCLUSIVE))
    report_window = (
        pd.Timestamp(datetime.fromisoformat(config.REPORT_WINDOW_START)),
        pd.Timestamp(datetime.fromisoformat(config.REPORT_WINDOW_END_EXCLUSIVE)),
    )
    # Record the partitions actually present before any defects are seeded;
    # this is the "expected manifest" missing_partition/stale_partition are
    # checked against, mirroring a real gate comparing today's batch to
    # yesterday's known-good partition list.
    expected_partitions = set(
        map(tuple, settlements[["state", "product"]].drop_duplicates().values)
    )
    ctx = {
        "as_of": as_of,
        "report_window": report_window,
        "expected_partitions": expected_partitions,
        "max_staleness_hours": config.FRESHNESS_MAX_STALENESS_HOURS,
    }

    ledger = []

    def log(defect_id, table, key_val, desc):
        ledger.append({"defect_id": defect_id, "table": table, "key": key_val, "description": desc})

    # A pool of "safe to mutate" settlement/leg row positions, well clear of
    # each other so one defect's mutation cannot mask or fake another's.
    n_settle = len(settlements)
    n_legs = len(legs)
    s_idx = iter(range(0, n_settle - 1))
    l_idx = iter(range(0, n_legs - 1))

    def next_s():
        return next(s_idx)

    def next_l():
        return next(l_idx)

    # 1. negative_handle
    i = next_s()
    settlements.loc[i, "stake"] = -50.0
    log("negative_handle", "settlements", settlements.loc[i, "bet_id"], "stake < 0")

    # 2. negative_payout
    i = next_s()
    settlements.loc[i, "payout"] = -10.0
    log("negative_payout", "settlements", settlements.loc[i, "bet_id"], "payout < 0")

    # 3. orphaned_settlement: settlement row with a bet_id no leg has
    orphan_bet_id = int(legs["bet_id"].max()) + 999_999
    orphan_row = settlements.iloc[[0]].copy()
    orphan_row["bet_id"] = orphan_bet_id
    settlements = pd.concat([settlements, orphan_row], ignore_index=True)
    log("orphaned_settlement", "settlements", orphan_bet_id, "bet_id has no matching leg rows")

    # 4. duplicate_bet_id
    i = next_s()
    dup_row = settlements.iloc[[i]].copy()
    settlements = pd.concat([settlements, dup_row], ignore_index=True)
    log("duplicate_bet_id", "settlements", settlements.loc[i, "bet_id"], "bet_id appears twice in settlements")

    # 5. missing_state
    i = next_s()
    settlements.loc[i, "state"] = None
    log("missing_state", "settlements", settlements.loc[i, "bet_id"], "state is null")

    # 6. missing_product
    i = next_s()
    settlements.loc[i, "product"] = None
    log("missing_product", "settlements", settlements.loc[i, "bet_id"], "product is null")

    # 7. invalid_state_code
    i = next_s()
    settlements.loc[i, "state"] = "ZZ"
    log("invalid_state_code", "settlements", settlements.loc[i, "bet_id"], "state not in legal-state universe")

    # 8. invalid_product
    i = next_s()
    settlements.loc[i, "product"] = "Darts"
    log("invalid_product", "settlements", settlements.loc[i, "bet_id"], "product not in product catalog")

    # 9. settlement_before_placed
    i = next_s()
    settlements.loc[i, "settled_ts"] = settlements.loc[i, "placed_ts"] - pd.Timedelta(hours=2)
    log("settlement_before_placed", "settlements", settlements.loc[i, "bet_id"], "settled_ts < placed_ts")

    # 10. stale_partition: push one whole (state, product) partition's max
    # placed_ts far outside the freshness window.
    stale_state, stale_product = sorted(expected_partitions)[0]
    stale_mask = (settlements["state"] == stale_state) & (settlements["product"] == stale_product)
    settlements.loc[stale_mask, "placed_ts"] = report_window[0] - pd.Timedelta(days=10)
    log("stale_partition", "settlements", f"{stale_state}|{stale_product}", "partition max placed_ts older than freshness threshold")

    # 11. missing_partition: drop one whole (state, product) partition
    miss_state, miss_product = sorted(expected_partitions)[1]
    keep_mask = ~((settlements["state"] == miss_state) & (settlements["product"] == miss_product))
    removed_bet_ids = set(settlements.loc[~keep_mask, "bet_id"])
    settlements = settlements.loc[keep_mask].reset_index(drop=True)
    legs = legs.loc[~legs["bet_id"].isin(removed_bet_ids)].reset_index(drop=True)
    log("missing_partition", "settlements", f"{miss_state}|{miss_product}", "partition entirely absent from the batch")

    # (indices shifted after the drop above; refresh iterators/positions)
    n_settle = len(settlements)
    s_idx = iter(range(2, n_settle - 1))

    # 12. mismatched_currency
    i = next_s()
    settlements.loc[i, "currency"] = "EUR"
    log("mismatched_currency", "settlements", settlements.loc[i, "bet_id"], "currency != USD")

    # 13. zero_stake
    i = next_s()
    settlements.loc[i, "stake"] = 0.0
    log("zero_stake", "settlements", settlements.loc[i, "bet_id"], "stake == 0")

    # 18. future_dated_bet
    i = next_s()
    settlements.loc[i, "placed_ts"] = as_of + pd.Timedelta(days=14)
    log("future_dated_bet", "settlements", settlements.loc[i, "bet_id"], "placed_ts after as-of time")

    # 19. null_customer_id
    i = next_s()
    settlements.loc[i, "customer_id"] = None
    log("null_customer_id", "settlements", settlements.loc[i, "bet_id"], "customer_id is null")

    # 28. customer_id_out_of_range
    i = next_s()
    settlements.loc[i, "customer_id"] = config.N_CUSTOMERS + 500_000
    log("customer_id_out_of_range", "settlements", settlements.loc[i, "bet_id"], "customer_id outside the simulated customer pool")

    # 21. invalid_settlement_outcome
    i = next_s()
    settlements.loc[i, "bet_outcome"] = "refunded"
    log("invalid_settlement_outcome", "settlements", settlements.loc[i, "bet_id"], "bet_outcome not in {win,loss,push,void}")

    # 25. void_with_nonzero_delta_payout
    void_rows = settlements.index[settlements["bet_outcome"] == "void"].tolist()
    i = void_rows[0]
    settlements.loc[i, "payout"] = settlements.loc[i, "stake"] * 2 + 25
    log("void_with_nonzero_delta_payout", "settlements", settlements.loc[i, "bet_id"], "void bet paid out != stake refund")

    # 22. payout_exceeds_theoretical_max
    i = next_s()
    settlements.loc[i, "payout"] = settlements.loc[i, "stake"] * 500 + 1000
    log("payout_exceeds_theoretical_max", "settlements", settlements.loc[i, "bet_id"], "payout above stake * product(all leg odds)")

    # 16. parlay_single_leg
    i = next_s()
    settlements.loc[i, "is_parlay"] = True
    settlements.loc[i, "num_legs"] = 1
    log("parlay_single_leg", "settlements", settlements.loc[i, "bet_id"], "is_parlay true but num_legs <= 1")

    # 29. leg_count_mismatch
    i = next_s()
    settlements.loc[i, "num_legs"] = int(settlements.loc[i, "num_legs"]) + 3
    log("leg_count_mismatch", "settlements", settlements.loc[i, "bet_id"], "num_legs disagrees with actual leg row count")

    # 30. timestamp_outside_report_window
    i = next_s()
    settlements.loc[i, "placed_ts"] = report_window[0] - pd.Timedelta(days=200)
    log("timestamp_outside_report_window", "settlements", settlements.loc[i, "bet_id"], "placed_ts outside the claimed report window")

    # 24. bet_missing_settlement: pick a bet_id that has legs, remove its
    # settlement row entirely.
    remaining_bet_ids = set(settlements["bet_id"]) - {orphan_bet_id}
    victim_bet_id = sorted(remaining_bet_ids)[-1]
    settlements = settlements[settlements["bet_id"] != victim_bet_id].reset_index(drop=True)
    log("bet_missing_settlement", "settlements", victim_bet_id, "bet has legs but no settlement row")

    # ---- leg-level defects ----
    j = next_l()
    legs.loc[j, "decimal_odds"] = 0.85
    log("odds_below_min", "legs", legs.loc[j, "leg_id"], "decimal_odds <= 1.0")

    j = next_l()
    legs.loc[j, "implied_prob"] = 1.15
    log("implied_prob_over_100", "legs", legs.loc[j, "leg_id"], "implied_prob > 1.0")

    j = next_l()
    legs.loc[j, "american_odds"] = 0
    log("zero_american_odds", "legs", legs.loc[j, "leg_id"], "american_odds == 0 (impossible)")

    j = next_l()
    legs.loc[j, "american_odds"] = None
    log("leg_missing_odds", "legs", legs.loc[j, "leg_id"], "american_odds is null")

    j = next_l()
    dup_leg = legs.iloc[[j]].copy()
    legs = pd.concat([legs, dup_leg], ignore_index=True)
    log("duplicate_leg_id", "legs", legs.loc[j, "leg_id"], "leg_id appears twice in fact_bet_legs")

    # 17. straight_multi_leg: give a straight (is_parlay=False, num_legs=1)
    # bet a second leg row in fact_bet_legs.
    straight_bets = settlements.index[(~settlements["is_parlay"]) & (settlements["num_legs"] == 1)]
    straight_bet_id = settlements.loc[straight_bets[5], "bet_id"]
    extra_leg = legs[legs["bet_id"] == straight_bet_id].iloc[[0]].copy()
    extra_leg["leg_id"] = extra_leg["leg_id"] + 1
    extra_leg["leg_no"] = 2
    legs = pd.concat([legs, extra_leg], ignore_index=True)
    log("straight_multi_leg", "legs", straight_bet_id, "is_parlay false but bet_id has >1 leg row")

    # 27. state_case_mismatch (on a settlement row, distinct from #7)
    i = next_s()
    orig_state = settlements.loc[i, "state"]
    if isinstance(orig_state, str):
        settlements.loc[i, "state"] = orig_state.lower()
    log("state_case_mismatch", "settlements", settlements.loc[i, "bet_id"], "state valid but wrong case")

    ledger_df = pd.DataFrame(ledger)
    assert ledger_df["defect_id"].nunique() == 30, (
        f"expected 30 distinct seeded defects, seeded {ledger_df['defect_id'].nunique()}"
    )
    return legs, settlements, ledger_df, ctx
