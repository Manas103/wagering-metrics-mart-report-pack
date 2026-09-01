"""Hand-computed metric checks: a tiny, fully-known settlements table where
the right answer for handle, actual hold, structural hold, parlay mix and
revenue per MUP is worked out by hand, then compared to mart.build_mart's
output. This is the test that would actually fail if a formula were wrong,
unlike an invariant test that can pass on internally-consistent-but-wrong
numbers.
"""
from __future__ import annotations

import duckdb

from wagering_mart import mart


def _load_known_batch(con):
    con.execute("""
        CREATE TABLE fact_settlements AS SELECT * FROM (VALUES
            -- bet_id, customer_id, state, product, is_parlay, num_legs, currency,
            -- stake, placed_ts, settled_ts, bet_outcome, payout, structural_hold
            (1, 100, 'NJ', 'NFL', false, 1, 'USD', 100.0,
                TIMESTAMP '2026-07-01 10:00:00', TIMESTAMP '2026-07-01 14:00:00', 'win', 180.0, 0.05),
            (2, 100, 'NJ', 'NFL', false, 1, 'USD', 50.0,
                TIMESTAMP '2026-07-05 10:00:00', TIMESTAMP '2026-07-05 14:00:00', 'loss', 0.0, 0.05),
            (3, 200, 'NJ', 'NFL', false, 1, 'USD', 200.0,
                TIMESTAMP '2026-07-10 10:00:00', TIMESTAMP '2026-07-10 14:00:00', 'push', 200.0, 0.05),
            (4, 300, 'NJ', 'Same Game Parlay', true, 3, 'USD', 20.0,
                TIMESTAMP '2026-07-12 10:00:00', TIMESTAMP '2026-07-12 20:00:00', 'win', 140.0, 0.20),
            (5, 300, 'NJ', 'Same Game Parlay', true, 2, 'USD', 30.0,
                TIMESTAMP '2026-07-20 10:00:00', TIMESTAMP '2026-07-20 20:00:00', 'loss', 0.0, 0.15)
        ) AS t(bet_id, customer_id, state, product, is_parlay, num_legs, currency,
                stake, placed_ts, settled_ts, bet_outcome, payout, structural_hold)
    """)


def test_metrics_match_hand_computation():
    con = duckdb.connect()
    _load_known_batch(con)
    mart.build_mart(con)
    rows = {
        (r[1], r[2]): r for r in con.execute(
            "SELECT year_month, state, product, handle, payout, net_revenue, actual_hold, "
            "structural_hold, parlay_handle, parlay_mix, unique_payers, revenue_per_mup "
            "FROM mart_metrics"
        ).fetchall()
    }

    nfl = rows[("NJ", "NFL")]
    # handle = 100 + 50 + 200 = 350 ; payout = 180 + 0 + 200 = 380
    assert nfl[3] == 350.0
    assert nfl[4] == 380.0
    assert nfl[5] == -30.0
    assert abs(nfl[6] - (-30.0 / 350.0)) < 1e-5
    assert abs(nfl[7] - 0.05) < 1e-5  # every NFL row has structural_hold 0.05
    assert nfl[8] == 0.0  # no parlay handle in this slice
    assert nfl[9] == 0.0
    assert nfl[10] == 2  # customers 100 and 200
    assert abs(nfl[11] - (-30.0 / 2)) < 1e-5

    sgp = rows[("NJ", "Same Game Parlay")]
    # handle = 20 + 30 = 50 ; payout = 140 + 0 = 140
    assert sgp[3] == 50.0
    assert sgp[4] == 140.0
    assert sgp[5] == -90.0
    assert abs(sgp[6] - (-90.0 / 50.0)) < 1e-5
    # structural hold, handle-weighted: (20*0.20 + 30*0.15) / 50
    expected_struct = (20 * 0.20 + 30 * 0.15) / 50
    assert abs(sgp[7] - expected_struct) < 1e-5
    assert sgp[8] == 50.0  # entire slice is parlay handle
    assert abs(sgp[9] - 1.0) < 1e-5
    assert sgp[10] == 1  # customer 300 only

    con.close()


def test_totals_aggregate_correctly():
    con = duckdb.connect()
    _load_known_batch(con)
    mart.build_mart(con)
    t = mart.totals(con)
    assert t["handle"] == 400.0        # 350 + 50
    assert t["payout"] == 520.0        # 380 + 140
    assert t["net_revenue"] == -120.0
    assert abs(t["actual_hold"] - (-120.0 / 400.0)) < 1e-5
    # parlay_mix = parlay handle (50) / total handle (400)
    assert abs(t["parlay_mix"] - (50.0 / 400.0)) < 1e-5
    con.close()
