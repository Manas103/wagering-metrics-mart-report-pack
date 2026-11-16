"""Full-scale freshness/completeness gate, run directly against the DuckDB
fact table with SQL aggregation (no pandas materialization), the same
technique wagering_mart/freshness.py uses to stay cheap enough to run
against a real multi-million-row batch on every refresh.

Freshness rule: for the report month, every (region, product, segment)
partition that is expected to exist must be present in
fact_pipeline_events, and its max(event_date) must be within
FRESHNESS_MAX_STALENESS_DAYS of the run's as-of date. Either condition
failing for any partition holds the whole publish, not just that
partition, for the same reason the wagering mart does it that way: a
partial mart is worse than a delayed one.
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
        v = [f"stale_partition:{r}|{p}|{s}" for r, p, s in self.stale_partitions]
        v += [f"missing_partition:{r}|{p}|{s}" for r, p, s in self.missing_partitions]
        return v


def expected_partitions() -> set:
    return {(r, p, s) for r in config.REGIONS for p in config.PRODUCTS for s in config.SEGMENTS}


def check_freshness(
    con: duckdb.DuckDBPyConnection,
    report_month: str = config.REPORT_MONTH,
    as_of: str | None = None,
    max_staleness_days: int = config.FRESHNESS_MAX_STALENESS_DAYS,
    table: str = "fact_pipeline_events",
) -> FreshnessResult:
    if as_of is None:
        as_of = str(con.execute(f"SELECT MAX(event_date) FROM {table}").fetchone()[0])

    rows = con.execute(f"""
        SELECT region, product, segment, MAX(event_date) AS max_date
        FROM {table}
        WHERE strftime(event_date, '%Y-%m') = ?
        GROUP BY 1, 2, 3
    """, [report_month]).fetchall()

    present = {(r, p, s): max_date for r, p, s, max_date in rows}
    expected = expected_partitions()
    missing = sorted(expected - set(present.keys()))

    stale = []
    as_of_date = con.execute("SELECT CAST(? AS DATE)", [as_of]).fetchone()[0]
    for (r, p, s), max_date in present.items():
        days_stale = (as_of_date - max_date).days
        if days_stale > max_staleness_days:
            stale.append((r, p, s))
    stale.sort()

    ok = (len(missing) == 0) and (len(stale) == 0)
    return FreshnessResult(ok=ok, stale_partitions=stale, missing_partitions=missing, as_of=as_of, report_month=report_month)


def inject_stale_demo(con: duckdb.DuckDBPyConnection, table: str = "fact_pipeline_events") -> str:
    """Deliberately ages one real (region, product, segment) partition of
    the already-generated batch by 10 days, for the demonstrated-refusal
    case. Mutates `table` in place."""
    row = con.execute(f"""
        SELECT region, product, segment FROM {table}
        WHERE strftime(event_date, '%Y-%m') = ?
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 3 LIMIT 1
    """, [config.REPORT_MONTH]).fetchone()
    region, product, segment = row
    con.execute(f"""
        UPDATE {table}
        SET event_date = event_date - INTERVAL 10 DAY
        WHERE region = ? AND product = ? AND segment = ?
          AND strftime(event_date, '%Y-%m') = ?
    """, [region, product, segment, config.REPORT_MONTH])
    return f"{region}|{product}|{segment}"
