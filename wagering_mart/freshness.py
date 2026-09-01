"""Full-scale freshness/completeness gate, run directly against the DuckDB
fact tables with SQL aggregation (no pandas materialization), so it is
cheap enough to run against the real 25M-row batch on every refresh.

Freshness rule (concrete, the one the resume bullet refers to): for the
report month, every (state, product) partition that is expected to exist
must be present, and its max(placed_ts) must be within
FRESHNESS_MAX_STALENESS_HOURS of the run's as-of time. Either condition
failing for any partition holds the whole publish, not just that
partition, because a partial mart is worse than a delayed one for a
regulator-adjacent report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from . import config


@dataclass
class FreshnessResult:
    ok: bool
    stale_partitions: list = field(default_factory=list)
    missing_partitions: list = field(default_factory=list)
    as_of: str = ""
    report_month: str = ""

    def violations(self) -> list:
        v = [f"stale_partition:{s}|{p}" for s, p in self.stale_partitions]
        v += [f"missing_partition:{s}|{p}" for s, p in self.missing_partitions]
        return v


def expected_partitions() -> set:
    return {(s, p) for s in config.STATES for p in config.PRODUCTS}


def check_freshness(
    con: duckdb.DuckDBPyConnection,
    report_month: str = config.REPORT_MONTH,
    as_of: str | None = None,
    max_staleness_hours: int = config.FRESHNESS_MAX_STALENESS_HOURS,
    table: str = "fact_settlements",
) -> FreshnessResult:
    if as_of is None:
        as_of = con.execute(f"SELECT MAX(placed_ts) FROM {table}").fetchone()[0]
        as_of = str(as_of)

    rows = con.execute(f"""
        SELECT state, product, MAX(placed_ts) AS max_ts
        FROM {table}
        WHERE strftime(placed_ts, '%Y-%m') = ?
        GROUP BY 1, 2
    """, [report_month]).fetchall()

    present = {(s, p): max_ts for s, p, max_ts in rows}
    expected = expected_partitions()

    missing = sorted(expected - set(present.keys()))

    stale = []
    as_of_ts_row = con.execute("SELECT CAST(? AS TIMESTAMP)", [as_of]).fetchone()[0]
    for (s, p), max_ts in present.items():
        hours_stale = (as_of_ts_row - max_ts).total_seconds() / 3600.0
        if hours_stale > max_staleness_hours:
            stale.append((s, p))
    stale.sort()

    ok = (len(missing) == 0) and (len(stale) == 0)
    return FreshnessResult(
        ok=ok, stale_partitions=stale, missing_partitions=missing,
        as_of=as_of, report_month=report_month,
    )


def inject_stale_demo(con: duckdb.DuckDBPyConnection, table: str = "fact_settlements") -> str:
    """Deliberately ages one real (state, product) partition of the ALREADY
    GENERATED batch by 10 days, for the demonstrated-refusal case. Returns
    the partition key that was aged. Mutates `table` in place; callers that
    need the untouched batch should run this against a disposable copy."""
    row = con.execute(f"""
        SELECT state, product FROM {table}
        WHERE strftime(placed_ts, '%Y-%m') = ?
        GROUP BY 1, 2 ORDER BY 1, 2 LIMIT 1
    """, [config.REPORT_MONTH]).fetchone()
    state, product = row
    con.execute(f"""
        UPDATE {table}
        SET placed_ts = placed_ts - INTERVAL 10 DAY
        WHERE state = ? AND product = ?
    """, [state, product])
    return f"{state}|{product}"
