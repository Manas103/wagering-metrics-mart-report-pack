"""Hand-computed metric checks for the sales-pipeline mart: a tiny,
fully-known pair of fact tables where the right answer for bookings, win
rate, cycle time, seller productivity, open pipeline and coverage ratio
is worked out by hand, then compared to mart.build_mart's output. This is
the test that would fail if a formula were wrong, not just an invariant
that can pass on internally-consistent-but-wrong numbers.
"""
from __future__ import annotations

import duckdb

from sales_pipeline_mart import mart


def _load_known_batch(con):
    con.execute("""
        CREATE TABLE fact_bookings_events AS SELECT * FROM (VALUES
            -- opp_id, region, product, segment, rep_id, amount, cycle_days, created_date, close_date, won
            (1, 'NA', 'Video', 'Enterprise', 1, 1000.0, 10, DATE '2026-09-01', DATE '2026-09-11', true),
            (2, 'NA', 'Video', 'Enterprise', 2, 2000.0, 20, DATE '2026-09-01', DATE '2026-09-21', true),
            (3, 'NA', 'Video', 'Enterprise', 1,  500.0, 30, DATE '2026-09-01', DATE '2026-09-30', false),
            (4, 'NA', 'Video', 'Enterprise', 1, 3000.0, 15, DATE '2026-10-01', DATE '2026-10-16', true),
            (5, 'NA', 'Video', 'Enterprise', 3,  400.0, 25, DATE '2026-10-01', DATE '2026-10-26', false)
        ) AS t(opp_id, region, product, segment, rep_id, amount, cycle_days, created_date, close_date, won)
    """)
    con.execute("""
        CREATE TABLE fact_pipeline_events AS SELECT * FROM (VALUES
            (6, 'NA', 'Video', 'Enterprise', 2,  500.0, DATE '2026-09-15', 2),
            (7, 'NA', 'Video', 'Enterprise', 2,  700.0, DATE '2026-09-20', 3),
            (8, 'NA', 'Video', 'Enterprise', 3,  900.0, DATE '2026-10-05', 1)
        ) AS t(opp_id, region, product, segment, rep_id, amount, event_date, stage)
    """)


def test_metrics_match_hand_computation():
    con = duckdb.connect()
    _load_known_batch(con)
    mart.build_mart(con)
    rows = {
        (r[0], r[1]): r[:2] + tuple(v if v is None else float(v) for v in r[2:]) for r in con.execute(
            "SELECT year_month, region, bookings, won_count, lost_count, win_rate, "
            "cycle_time_days, active_reps, seller_productivity, open_pipeline, coverage_ratio "
            "FROM mart_metrics ORDER BY year_month"
        ).fetchall()
    }

    sep = rows[("2026-09", "NA")]
    assert abs(sep[2] - 3000.0) < 0.01     # bookings = 1000 + 2000
    assert sep[3] == 2 and sep[4] == 1     # won, lost
    assert abs(sep[5] - (2 / 3)) < 1e-6    # win_rate
    assert abs(sep[6] - 20.0) < 1e-6       # cycle_time_days = avg(10, 20, 30)
    assert sep[7] == 2                     # active_reps (rep 1, rep 2)
    assert abs(sep[8] - 1500.0) < 0.01     # seller_productivity = 3000 / 2
    assert abs(sep[9] - 1200.0) < 0.01     # open_pipeline = 500 + 700
    assert sep[10] is None                 # no preceding month, coverage undefined

    oct_ = rows[("2026-10", "NA")]
    assert abs(oct_[2] - 3000.0) < 0.01    # bookings = 3000
    assert oct_[3] == 1 and oct_[4] == 1
    assert abs(oct_[5] - 0.5) < 1e-6
    assert abs(oct_[6] - 20.0) < 1e-6      # avg(15, 25)
    assert oct_[7] == 2                    # rep 1, rep 3
    assert abs(oct_[8] - 1500.0) < 0.01
    assert abs(oct_[9] - 900.0) < 0.01     # open_pipeline = 900
    assert abs(oct_[10] - (900.0 / 3000.0)) < 1e-6  # coverage vs the one preceding month
    con.close()
