"""Reconciliation invariants between the raw fact tables and the mart, on a
small-but-real generated batch (not the 25M-row batch; tests must stay
fast). See scripts/run_benchmark.py / docs/measurement_output.txt for the
same invariants re-checked at full 25M-row scale.
"""
from __future__ import annotations

import duckdb
import pytest

from wagering_mart import generate, mart

N_LEGS = 150_000


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    generate.generate(c, target_legs=N_LEGS)
    mart.build_mart(c)
    yield c
    c.close()


def test_leg_and_bet_counts_are_positive(con):
    n_legs = con.execute("SELECT COUNT(*) FROM fact_bet_legs").fetchone()[0]
    n_bets = con.execute("SELECT COUNT(*) FROM fact_settlements").fetchone()[0]
    assert n_legs > 0
    assert n_bets > 0
    assert n_legs >= n_bets  # every bet has >= 1 leg


def test_handle_reconciles_raw_to_mart(con):
    raw_handle = con.execute("SELECT ROUND(SUM(stake), 2) FROM fact_settlements").fetchone()[0]
    mart_handle = con.execute("SELECT ROUND(SUM(handle), 2) FROM mart_metrics").fetchone()[0]
    assert abs(raw_handle - mart_handle) < 0.01


def test_bet_count_reconciles_raw_to_mart(con):
    raw_n = con.execute("SELECT COUNT(*) FROM fact_settlements").fetchone()[0]
    mart_n = con.execute("SELECT SUM(bet_count) FROM mart_metrics").fetchone()[0]
    assert raw_n == mart_n


def test_num_legs_matches_actual_leg_rows_for_clean_batch(con):
    mismatch = con.execute("""
        SELECT COUNT(*) FROM fact_settlements s
        JOIN (SELECT bet_id, COUNT(*) AS n FROM fact_bet_legs GROUP BY 1) l
        USING (bet_id)
        WHERE s.num_legs != l.n
    """).fetchone()[0]
    assert mismatch == 0


def test_straight_bets_have_exactly_one_leg(con):
    bad = con.execute("""
        SELECT COUNT(*) FROM fact_settlements s
        JOIN (SELECT bet_id, COUNT(*) AS n FROM fact_bet_legs GROUP BY 1) l USING (bet_id)
        WHERE NOT s.is_parlay AND l.n != 1
    """).fetchone()[0]
    assert bad == 0


def test_parlay_bets_have_two_to_six_legs(con):
    bad = con.execute("""
        SELECT COUNT(*) FROM fact_settlements
        WHERE is_parlay AND (num_legs < 2 OR num_legs > 6)
    """).fetchone()[0]
    assert bad == 0


def test_structural_hold_is_between_0_and_1(con):
    row = con.execute("SELECT MIN(structural_hold), MAX(structural_hold) FROM fact_settlements").fetchone()
    lo, hi = row
    assert lo > 0
    assert hi < 1


def test_actual_hold_is_plausible_for_a_sportsbook(con):
    # Not a tautology: a broken payout/odds formula would push this well
    # outside a real book's realized-hold range even though it is a "real"
    # measured number on a random batch, which is exactly the kind of bug
    # this invariant is meant to catch.
    row = con.execute(
        "SELECT (SUM(stake) - SUM(payout)) / SUM(stake) FROM fact_settlements"
    ).fetchone()[0]
    assert -0.05 < row < 0.30


def test_parlay_mix_plus_straight_mix_equals_one(con):
    row = con.execute("""
        SELECT
            SUM(CASE WHEN is_parlay THEN stake ELSE 0 END) / SUM(stake) AS parlay_mix,
            SUM(CASE WHEN NOT is_parlay THEN stake ELSE 0 END) / SUM(stake) AS straight_mix
        FROM fact_settlements
    """).fetchone()
    parlay_mix, straight_mix = row
    assert abs((parlay_mix + straight_mix) - 1.0) < 1e-9


def test_no_settlement_before_placement_in_clean_batch(con):
    bad = con.execute("SELECT COUNT(*) FROM fact_settlements WHERE settled_ts < placed_ts").fetchone()[0]
    assert bad == 0


def test_payout_never_exceeds_theoretical_max_in_clean_batch(con):
    bad = con.execute("""
        WITH max_mult AS (
            SELECT bet_id, EXP(SUM(LN(decimal_odds))) AS m FROM fact_bet_legs GROUP BY 1
        )
        SELECT COUNT(*) FROM fact_settlements s JOIN max_mult USING (bet_id)
        WHERE s.payout > s.stake * m * 1.0001 + 0.01
    """).fetchone()[0]
    assert bad == 0


def test_american_and_decimal_odds_are_consistent(con):
    bad = con.execute("""
        SELECT COUNT(*) FROM fact_bet_legs
        WHERE (decimal_odds >= 2 AND ABS(american_odds - ROUND((decimal_odds - 1) * 100)) > 1)
           OR (decimal_odds < 2 AND ABS(american_odds - ROUND(-100 / (decimal_odds - 1))) > 1)
    """).fetchone()[0]
    assert bad == 0
