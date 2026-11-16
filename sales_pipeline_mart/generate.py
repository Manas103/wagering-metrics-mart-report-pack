"""Vectorized synthetic generation of the pipeline event log and bookings
events. Everything here runs as DuckDB SQL over range()/generate_series(),
never a Python row-by-row loop, the same technique wagering_mart/generate.py
uses to explode bets to legs: here an opportunity explodes to one daily
pipeline-snapshot event per day it is open, via a lateral generate_series()
join.

Two fact tables come out:

  fact_pipeline_events  one row per (opportunity, day) it was open: which
                        stage it was in that day, region, product, segment.
  fact_bookings_events  one row per opportunity's close (win or loss), the
                        grain bookings and win-rate are computed from.

A random() call is never repeated textually inside a CASE expression; every
draw is materialized into its own column first, per the same rule
wagering_mart/generate.py documents (a repeated bare random() would redraw
per branch and silently break the weighting).
"""
from __future__ import annotations

import time
from datetime import datetime

import duckdb

from wagering_mart.genutil import weighted_case

from . import config

STAGE_DAY_SHARE = {1: 0.30, 2: 0.25, 3: 0.25, 4: 0.20}


def _window_days() -> int:
    start = datetime.fromisoformat(config.REPORT_WINDOW_START)
    end = datetime.fromisoformat(config.REPORT_WINDOW_END_EXCLUSIVE)
    return (end - start).days


def generate(con: duckdb.DuckDBPyConnection, n_opportunities: int = config.N_OPPORTUNITIES) -> dict:
    """Generates both fact tables in-place on `con`. Returns a dict of
    timing / row-count measurements for the honest benchmark report."""
    con.execute(f"PRAGMA threads={config.MAX_THREADS}")
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"SELECT setseed({config.RNG_SEED % 2147483647 / 2147483647.0})")

    window_days = _window_days()
    region_case = weighted_case("r_region", config.REGION_WEIGHTS)
    product_case = weighted_case("r_product", config.PRODUCT_WEIGHTS)
    segment_case = weighted_case("r_segment", config.SEGMENT_WEIGHTS)

    t0 = time.perf_counter()

    # ---- stage 1: opportunity-level draws -----------------------------
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_opps_raw AS
        SELECT
            opp_id,
            random() AS r_region, random() AS r_product, random() AS r_segment,
            CAST(floor(random() * {config.N_REPS}) AS INTEGER) AS rep_id,
            random() AS r_created, random() AS r_amount, random() AS r_amount2,
            random() AS r_speed, random() AS r_speed2, random() AS r_outcome
        FROM range({n_opportunities}) t(opp_id)
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE stg_opps AS
        SELECT
            opp_id, rep_id,
            {region_case} AS region,
            {product_case} AS product,
            {segment_case} AS segment,
            DATE '{config.REPORT_WINDOW_START}' + CAST(r_created * {window_days} AS INTEGER) AS created_date,
            -- Box-Muller from the already-materialized amount draws, lognormal amount by segment.
            sqrt(-2 * ln(greatest(r_amount, 1e-9))) * cos(2 * pi() * r_amount2) AS _z_amount,
            -- Independent Box-Muller for speed_factor from the speed draws.
            LEAST(GREATEST(exp({config.SPEED_FACTOR_SIGMA} *
                sqrt(-2 * ln(greatest(r_speed, 1e-9))) * sin(2 * pi() * r_speed2)), 0.3), 3.0) AS speed_factor,
            r_outcome
        FROM stg_opps_raw
    """)
    con.execute("DROP TABLE stg_opps_raw")

    seg_case_amount = " ".join(
        f"WHEN segment = '{seg}' THEN {scale}" for seg, scale in config.AMOUNT_SCALE.items()
    )
    seg_case_cycle = " ".join(
        f"WHEN segment = '{seg}' THEN {days}" for seg, days in config.SEGMENT_TYPICAL_CYCLE_DAYS.items()
    )
    seg_case_winrate = " ".join(
        f"WHEN segment = '{seg}' THEN {rate}" for seg, rate in config.SEGMENT_BASE_WIN_RATE.items()
    )

    con.execute(f"""
        CREATE OR REPLACE TABLE stg_opps2 AS
        SELECT
            opp_id, rep_id, region, product, segment, created_date, speed_factor, r_outcome,
            ROUND(GREATEST((CASE {seg_case_amount} END) * exp(0.55 * _z_amount), 300.0), 2) AS amount,
            GREATEST(CAST(ROUND((CASE {seg_case_cycle} END) * speed_factor) AS INTEGER), 4) AS cycle_days,
            LEAST(GREATEST((CASE {seg_case_winrate} END) * (1 + 0.6 * (1 - speed_factor)), 0.02), 0.95) AS win_prob
        FROM stg_opps
    """)
    con.execute("DROP TABLE stg_opps")

    con.execute("""
        CREATE OR REPLACE TABLE fact_opportunities AS
        SELECT
            opp_id, rep_id, region, product, segment, created_date, cycle_days, amount, speed_factor,
            created_date + CAST(cycle_days AS INTEGER) AS close_date,
            (r_outcome < win_prob) AS won
        FROM stg_opps2
    """)
    con.execute("DROP TABLE stg_opps2")

    # ---- stage 2: explode each opportunity to one event per open day --
    stage_bounds = []
    cum = 0.0
    for stage, share in STAGE_DAY_SHARE.items():
        cum += share
        stage_bounds.append((stage, cum))
    stage_case = " ".join(
        f"WHEN day_offset < cycle_days * {bound} THEN {stage}" for stage, bound in stage_bounds[:-1]
    )

    # Both fact tables are truncated at the report window's end: an
    # opportunity whose close_date would otherwise fall on or after that
    # date simply has not closed yet as of this snapshot, so it is still
    # open pipeline, not a booking, and its event log stops at the window
    # boundary rather than projecting days that have not happened yet.
    con.execute(f"""
        CREATE OR REPLACE TABLE fact_pipeline_events AS
        SELECT
            o.opp_id, o.region, o.product, o.segment, o.rep_id, o.amount,
            o.created_date + CAST(d.day_offset AS INTEGER) AS event_date,
            CASE {stage_case} ELSE 4 END AS stage
        FROM fact_opportunities o, generate_series(0, o.cycle_days - 1) AS d(day_offset)
        WHERE o.created_date + CAST(d.day_offset AS INTEGER) < DATE '{config.REPORT_WINDOW_END_EXCLUSIVE}'
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE fact_bookings_events AS
        SELECT
            opp_id, region, product, segment, rep_id, amount, cycle_days,
            created_date, close_date, won
        FROM fact_opportunities
        WHERE close_date < DATE '{config.REPORT_WINDOW_END_EXCLUSIVE}'
    """)

    n_pipeline = con.execute("SELECT COUNT(*) FROM fact_pipeline_events").fetchone()[0]
    n_bookings = con.execute("SELECT COUNT(*) FROM fact_bookings_events").fetchone()[0]
    elapsed = time.perf_counter() - t0

    return {
        "n_opportunities": n_opportunities,
        "n_pipeline_events": n_pipeline,
        "n_bookings_events": n_bookings,
        "n_total_events": n_pipeline + n_bookings,
        "elapsed_seconds": round(elapsed, 2),
    }


if __name__ == "__main__":
    config.ensure_dirs()
    con = duckdb.connect(str(config.PIPELINE_DB_PATH))
    stats = generate(con)
    print(stats)
    con.close()
