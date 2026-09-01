"""Builds the one flat, pivot-ready metrics table the Excel pack and the
Streamlit dashboard both read. Grain: (year_month, state, product).

Every column here has exactly one definition, in docs/METRIC_DEFINITIONS.md;
this module is the only place any of them is computed, so there is no way
for two call sites to compute "hold" two different ways.
"""
from __future__ import annotations

import duckdb

MART_SQL = """
CREATE OR REPLACE TABLE mart_metrics AS
SELECT
    strftime(placed_ts, '%Y-%m') AS year_month,
    state,
    product,
    COUNT(*) AS bet_count,
    ROUND(SUM(stake), 2) AS handle,
    ROUND(SUM(payout), 2) AS payout,
    ROUND(SUM(stake) - SUM(payout), 2) AS net_revenue,
    ROUND((SUM(stake) - SUM(payout)) / NULLIF(SUM(stake), 0), 6) AS actual_hold,
    ROUND(SUM(stake * structural_hold) / NULLIF(SUM(stake), 0), 6) AS structural_hold,
    ROUND(SUM(CASE WHEN is_parlay THEN stake ELSE 0 END), 2) AS parlay_handle,
    ROUND(SUM(CASE WHEN is_parlay THEN stake ELSE 0 END) / NULLIF(SUM(stake), 0), 6) AS parlay_mix,
    COUNT(DISTINCT customer_id) AS unique_payers,
    ROUND(
        (SUM(stake) - SUM(payout)) / NULLIF(COUNT(DISTINCT customer_id), 0), 2
    ) AS revenue_per_mup
FROM fact_settlements
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""


def build_mart(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(MART_SQL)
    return con.execute("SELECT COUNT(*) FROM mart_metrics").fetchone()[0]


def totals(con: duckdb.DuckDBPyConnection) -> dict:
    """Headline, whole-batch numbers (not sliced), used in the README table
    and as the one bold number in "measured results"."""
    row = con.execute("""
        SELECT
            COUNT(*) AS bets,
            ROUND(SUM(handle), 2) AS handle,
            ROUND(SUM(payout), 2) AS payout,
            ROUND(SUM(net_revenue), 2) AS net_revenue,
            ROUND(SUM(net_revenue) / NULLIF(SUM(handle), 0), 6) AS actual_hold,
            ROUND(SUM(handle * structural_hold) / NULLIF(SUM(handle), 0), 6) AS structural_hold,
            ROUND(SUM(parlay_handle) / NULLIF(SUM(handle), 0), 6) AS parlay_mix
        FROM mart_metrics
    """).fetchone()
    cols = ["bet_count", "handle", "payout", "net_revenue", "actual_hold", "structural_hold", "parlay_mix"]
    return dict(zip(cols, row))
