"""Reconciliation invariants between the raw fact tables and the mart, on
a small-but-real generated batch (not the ~23M-row batch; tests must stay
fast). See scripts/run_pipeline_benchmark.py / docs/pipeline_measurement_output.txt
for the same batch re-checked at full scale.
"""
from __future__ import annotations

import duckdb
import pytest

from sales_pipeline_mart import config, generate, mart

N_OPPORTUNITIES = 20_000


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    generate.generate(c, n_opportunities=N_OPPORTUNITIES)
    mart.build_mart(c)
    yield c
    c.close()


def test_opportunity_and_event_counts_are_positive(con):
    n_pipeline = con.execute("SELECT COUNT(*) FROM fact_pipeline_events").fetchone()[0]
    n_bookings = con.execute("SELECT COUNT(*) FROM fact_bookings_events").fetchone()[0]
    assert n_pipeline > 0
    assert n_bookings > 0


def test_every_bookings_opp_is_either_won_or_lost(con):
    bad = con.execute("SELECT COUNT(*) FROM fact_bookings_events WHERE won NOT IN (TRUE, FALSE)").fetchone()[0]
    assert bad == 0


def test_cycle_days_and_amounts_are_positive(con):
    neg_cycle = con.execute("SELECT COUNT(*) FROM fact_bookings_events WHERE cycle_days <= 0").fetchone()[0]
    neg_amount = con.execute("SELECT COUNT(*) FROM fact_bookings_events WHERE amount <= 0").fetchone()[0]
    assert neg_cycle == 0
    assert neg_amount == 0


def test_close_date_never_precedes_created_date(con):
    bad = con.execute("SELECT COUNT(*) FROM fact_bookings_events WHERE close_date < created_date").fetchone()[0]
    assert bad == 0


def test_every_stage_is_in_the_valid_range(con):
    bad = con.execute(f"""
        SELECT COUNT(*) FROM fact_pipeline_events
        WHERE stage NOT IN ({','.join(str(s) for s in config.STAGES)})
    """).fetchone()[0]
    assert bad == 0


def test_bookings_reconciles_raw_to_mart(con):
    raw_bookings = con.execute("SELECT ROUND(SUM(CASE WHEN won THEN amount ELSE 0 END), 2) FROM fact_bookings_events").fetchone()[0]
    mart_bookings = con.execute("SELECT ROUND(SUM(bookings), 2) FROM mart_metrics").fetchone()[0]
    assert abs(raw_bookings - mart_bookings) < 0.01


def test_won_plus_lost_count_reconciles_raw_to_mart(con):
    raw_n = con.execute("SELECT COUNT(*) FROM fact_bookings_events").fetchone()[0]
    mart_n = con.execute("SELECT SUM(won_count) + SUM(lost_count) FROM mart_metrics").fetchone()[0]
    assert raw_n == mart_n


def test_no_pipeline_events_outside_the_report_window(con):
    bad = con.execute(f"""
        SELECT COUNT(*) FROM fact_pipeline_events
        WHERE event_date < DATE '{config.REPORT_WINDOW_START}' OR event_date >= DATE '{config.REPORT_WINDOW_END_EXCLUSIVE}'
    """).fetchone()[0]
    assert bad == 0
