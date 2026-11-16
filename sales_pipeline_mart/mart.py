"""Builds the one flat, pivot-ready sales-pipeline metrics table, the same
"one definition, one place" discipline wagering_mart/mart.py uses for the
wagering mart. Grain: (year_month, region, product, segment).

Every column here has exactly one definition, written out in
docs/PIPELINE_METRIC_DEFINITIONS.md; this module is the only place any of
them is computed.
"""
from __future__ import annotations

import duckdb

BOOKINGS_SQL = """
CREATE OR REPLACE TABLE _bookings_agg AS
SELECT
    strftime(close_date, '%Y-%m') AS year_month,
    region, product, segment,
    ROUND(SUM(CASE WHEN won THEN amount ELSE 0 END), 2) AS bookings,
    SUM(CASE WHEN won THEN 1 ELSE 0 END) AS won_count,
    SUM(CASE WHEN NOT won THEN 1 ELSE 0 END) AS lost_count,
    ROUND(AVG(cycle_days), 2) AS cycle_time_days,
    COUNT(DISTINCT rep_id) AS active_reps
FROM fact_bookings_events
GROUP BY 1, 2, 3, 4
"""

OPEN_PIPELINE_SQL = """
CREATE OR REPLACE TABLE _open_pipeline_agg AS
WITH opp_month AS (
    SELECT DISTINCT opp_id, strftime(event_date, '%Y-%m') AS year_month, region, product, segment, amount
    FROM fact_pipeline_events
)
SELECT year_month, region, product, segment, ROUND(SUM(amount), 2) AS open_pipeline
FROM opp_month
GROUP BY 1, 2, 3, 4
"""

MART_SQL = """
CREATE OR REPLACE TABLE mart_metrics AS
SELECT
    COALESCE(b.year_month, p.year_month) AS year_month,
    COALESCE(b.region, p.region) AS region,
    COALESCE(b.product, p.product) AS product,
    COALESCE(b.segment, p.segment) AS segment,
    COALESCE(b.bookings, 0.0) AS bookings,
    COALESCE(b.won_count, 0) AS won_count,
    COALESCE(b.lost_count, 0) AS lost_count,
    ROUND(COALESCE(b.won_count, 0) / NULLIF(COALESCE(b.won_count, 0) + COALESCE(b.lost_count, 0), 0), 6) AS win_rate,
    b.cycle_time_days,
    COALESCE(b.active_reps, 0) AS active_reps,
    ROUND(COALESCE(b.bookings, 0.0) / NULLIF(COALESCE(b.active_reps, 0), 0), 2) AS seller_productivity,
    COALESCE(p.open_pipeline, 0.0) AS open_pipeline,
    ROUND(
        COALESCE(p.open_pipeline, 0.0) / NULLIF(
            AVG(COALESCE(b.bookings, 0.0)) OVER (
                PARTITION BY COALESCE(b.region, p.region), COALESCE(b.product, p.product), COALESCE(b.segment, p.segment)
                ORDER BY COALESCE(b.year_month, p.year_month)
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
            ), 0
        ), 4
    ) AS coverage_ratio
FROM _bookings_agg b
FULL OUTER JOIN _open_pipeline_agg p
    ON b.year_month = p.year_month AND b.region = p.region AND b.product = p.product AND b.segment = p.segment
ORDER BY 1, 2, 3, 4
"""


def build_mart(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(BOOKINGS_SQL)
    con.execute(OPEN_PIPELINE_SQL)
    con.execute(MART_SQL)
    con.execute("DROP TABLE _bookings_agg")
    con.execute("DROP TABLE _open_pipeline_agg")
    return con.execute("SELECT COUNT(*) FROM mart_metrics").fetchone()[0]


def totals(con: duckdb.DuckDBPyConnection) -> dict:
    """Headline, whole-book numbers (not sliced), used in the README table."""
    row = con.execute("""
        SELECT
            ROUND(SUM(bookings), 2) AS bookings,
            SUM(won_count) AS won_count,
            SUM(lost_count) AS lost_count,
            ROUND(SUM(won_count) / NULLIF(SUM(won_count) + SUM(lost_count), 0), 6) AS win_rate,
            ROUND(SUM(bookings * cycle_time_days) / NULLIF(SUM(bookings), 0), 2) AS cycle_time_days_weighted,
            ROUND(SUM(bookings) / NULLIF(SUM(active_reps), 0), 2) AS seller_productivity
        FROM mart_metrics
    """).fetchone()
    cols = ["bookings", "won_count", "lost_count", "win_rate", "cycle_time_days_weighted", "seller_productivity"]
    return dict(zip(cols, row))
