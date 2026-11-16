"""The stage-regression check: a pipeline funnel can only move forward
(Prospecting -> Qualification -> Proposal -> Negotiation), never backward,
in this simulated world (no "re-opened" opportunities are modeled). An
opportunity whose logged stage decreases between two consecutive event
dates is a data-quality break specific to pipeline data, with no
equivalent in the wagering mart this repo extends, run as one SQL
aggregation over the full event table so it is cheap enough for every
refresh, the same way freshness.py is.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb


@dataclass
class StageRegressionResult:
    ok: bool
    opportunities_checked: int = 0
    regressed_opportunity_ids: list = field(default_factory=list)

    def violations(self) -> list:
        return [f"stage_regression:opp_id={i}" for i in self.regressed_opportunity_ids]


def check_stage_regressions(con: duckdb.DuckDBPyConnection, table: str = "fact_pipeline_events") -> StageRegressionResult:
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _stage_lag AS
        SELECT
            opp_id, event_date, stage,
            LAG(stage) OVER (PARTITION BY opp_id ORDER BY event_date) AS prev_stage
        FROM {table}
    """)
    checked = con.execute(f"SELECT COUNT(DISTINCT opp_id) FROM {table}").fetchone()[0]
    regressed = con.execute("""
        SELECT DISTINCT opp_id FROM _stage_lag WHERE prev_stage IS NOT NULL AND stage < prev_stage ORDER BY 1
    """).fetchall()
    con.execute("DROP TABLE _stage_lag")
    regressed_ids = [r[0] for r in regressed]
    return StageRegressionResult(ok=len(regressed_ids) == 0, opportunities_checked=checked, regressed_opportunity_ids=regressed_ids)


def inject_regression_demo(con: duckdb.DuckDBPyConnection, table: str = "fact_pipeline_events") -> int:
    """Deliberately flips the stage of one real opportunity's middle event
    back to stage 1, for the demonstrated-refusal case. Returns the
    opp_id that was mutated."""
    opp_id = con.execute(f"""
        SELECT opp_id FROM {table} GROUP BY opp_id HAVING COUNT(*) >= 5 ORDER BY opp_id LIMIT 1
    """).fetchone()[0]
    mid_date = con.execute(f"""
        SELECT event_date FROM {table} WHERE opp_id = ? ORDER BY event_date
        LIMIT 1 OFFSET (SELECT COUNT(*) / 2 FROM {table} WHERE opp_id = ?)
    """, [opp_id, opp_id]).fetchone()[0]
    con.execute(f"UPDATE {table} SET stage = 1 WHERE opp_id = ? AND event_date = ?", [opp_id, mid_date])
    return opp_id
