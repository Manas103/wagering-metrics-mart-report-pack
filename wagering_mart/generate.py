"""Vectorized synthetic generation of bet legs and settlements.

Everything here runs as DuckDB SQL over range()/generate_series(), never a
Python row-by-row loop. Two fact tables come out:

  fact_bet_legs   one row per leg (a leg = one selection in a bet slip; a
                  straight bet has exactly 1 leg, a parlay has 2-6).
  fact_settlements one row per BET (wager), the grain a sportsbook actually
                  pays out at. Handle is defined from this table's `stake`
                  column, never by summing leg rows, or a 4-leg parlay would
                  be counted as 4x its real handle.

Random numbers are drawn once into a named column per logical decision and
then reused by reference; a random() call textually repeated inside a CASE
expression would redraw on every branch and silently break the weighting,
so every draw is materialized as its own column first.
"""
from __future__ import annotations

import time
from datetime import datetime

import duckdb

from . import config
from .genutil import weighted_case


def _window_seconds() -> int:
    start = datetime.fromisoformat(config.REPORT_WINDOW_START)
    end = datetime.fromisoformat(config.REPORT_WINDOW_END_EXCLUSIVE)
    return int((end - start).total_seconds())


def _n_bets_for_target_legs(target_legs: int) -> int:
    avg_parlay_legs = (config.PARLAY_MIN_LEGS + config.PARLAY_MAX_LEGS) / 2.0
    avg_legs_per_bet = (
        (1 - config.PARLAY_BET_SHARE) * 1.0 + config.PARLAY_BET_SHARE * avg_parlay_legs
    )
    return int(round(target_legs / avg_legs_per_bet))


def generate(con: duckdb.DuckDBPyConnection, target_legs: int = config.TARGET_LEG_COUNT) -> dict:
    """Generate the two fact tables in-place on `con`. Returns a dict of
    timing / row-count measurements for the honest benchmark report."""
    con.execute(f"PRAGMA threads={config.MAX_THREADS}")

    n_bets = _n_bets_for_target_legs(target_legs)
    window_seconds = _window_seconds()

    t0 = time.perf_counter()

    state_case = weighted_case("r_state", config.STATE_WEIGHTS)
    product_case = weighted_case("r_product", config.STRAIGHT_PRODUCT_WEIGHTS)

    # ---- stage 1: bet-level draws -----------------------------------
    con.execute(f"""
        CREATE OR REPLACE TABLE stg_bets_raw AS
        SELECT
            bet_id,
            random() AS r_customer,
            random() AS r_parlay,
            random() AS r_num_legs,
            random() AS r_state,
            random() AS r_product,
            random() AS r_stake_tier,
            random() AS r_stake_tier2,
            random() AS r_stake_whale,
            random() AS r_placed,
            random() AS r_settle_offset,
            random() AS r_void
        FROM range({n_bets}) t(bet_id)
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE stg_bets AS
        SELECT
            bet_id,
            CAST(floor(r_customer * {config.N_CUSTOMERS}) AS BIGINT) AS customer_id,
            (r_parlay < {config.PARLAY_BET_SHARE}) AS is_parlay,
            CASE WHEN r_parlay < {config.PARLAY_BET_SHARE}
                 THEN CAST(2 + floor(r_num_legs * 5) AS INTEGER)
                 ELSE 1 END AS num_legs,
            {state_case} AS state,
            CASE WHEN r_parlay < {config.PARLAY_BET_SHARE} THEN '{config.PARLAY_PRODUCT}'
                 ELSE {product_case} END AS product,
            ROUND(
                CASE WHEN r_stake_whale < 0.05
                     THEN (5 + r_stake_tier * 195) * (3 + r_stake_tier2 * 15)
                     ELSE (5 + r_stake_tier * 195) END
            , 2) AS stake,
            TIMESTAMP '{config.REPORT_WINDOW_START} 00:00:00'
                + CAST(r_placed * {window_seconds} AS BIGINT) * INTERVAL 1 SECOND AS placed_ts,
            (r_void < 0.003) AS is_void,
            r_settle_offset
        FROM stg_bets_raw
    """)
    con.execute("""
        CREATE OR REPLACE TABLE stg_bets2 AS
        SELECT *,
            placed_ts + CAST(30 + r_settle_offset * 2850 AS BIGINT) * INTERVAL 1 MINUTE AS settled_ts
        FROM stg_bets
    """)
    con.execute("DROP TABLE stg_bets_raw")
    con.execute("DROP TABLE stg_bets")

    # ---- stage 2: explode to legs, draw leg-level odds/outcome -------
    con.execute("""
        CREATE OR REPLACE TABLE stg_legs_raw AS
        SELECT
            b.bet_id, b.leg_no, b.state, b.product, b.placed_ts,
            random() AS r_true_prob,
            random() AS r_vig,
            random() AS r_outcome
        FROM (
            SELECT t.*, gs.leg_no
            FROM stg_bets2 t, generate_series(1, t.num_legs) AS gs(leg_no)
        ) b
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE fact_bet_legs AS
        SELECT
            bet_id * 10 + leg_no AS leg_id,
            bet_id,
            leg_no,
            state,
            product,
            placed_ts,
            '{config.CURRENCY}' AS currency,
            ROUND(0.30 + r_true_prob * 0.40, 6) AS true_win_prob,
            ROUND(0.04 + r_vig * 0.05, 6) AS vig,
            LEAST(ROUND((0.30 + r_true_prob * 0.40) * (1 + (0.04 + r_vig * 0.05)), 6), 0.98) AS implied_prob,
            1.0 / LEAST(ROUND((0.30 + r_true_prob * 0.40) * (1 + (0.04 + r_vig * 0.05)), 6), 0.98) AS decimal_odds,
            r_outcome AS _r_outcome
        FROM stg_legs_raw
    """)
    con.execute("DROP TABLE stg_legs_raw")

    con.execute("""
        CREATE OR REPLACE TABLE fact_bet_legs AS
        SELECT
            leg_id, bet_id, leg_no, state, product, placed_ts, currency,
            true_win_prob, vig, implied_prob,
            ROUND(decimal_odds, 6) AS decimal_odds,
            CASE WHEN decimal_odds >= 2 THEN ROUND((decimal_odds - 1) * 100)
                 ELSE ROUND(-100 / (decimal_odds - 1)) END AS american_odds,
            ROUND(1 - true_win_prob * decimal_odds, 6) AS leg_structural_hold,
            CASE WHEN _r_outcome < true_win_prob THEN 'win'
                 WHEN _r_outcome < true_win_prob + 0.02 THEN 'push'
                 ELSE 'loss' END AS leg_outcome
        FROM fact_bet_legs
    """)

    # ---- stage 3: aggregate legs -> bet-level settlement --------------
    con.execute("""
        CREATE OR REPLACE TABLE _leg_agg AS
        SELECT
            bet_id,
            SUM(CASE WHEN leg_outcome = 'loss' THEN 1 ELSE 0 END) AS n_loss,
            SUM(CASE WHEN leg_outcome = 'win' THEN 1 ELSE 0 END) AS n_win,
            SUM(CASE WHEN leg_outcome = 'win' THEN LN(decimal_odds) ELSE 0 END) AS ln_win_odds_sum,
            SUM(LN(true_win_prob) + LN(decimal_odds)) AS struct_ln_sum
        FROM fact_bet_legs
        GROUP BY bet_id
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE fact_settlements AS
        SELECT
            b.bet_id,
            b.customer_id,
            b.state,
            b.product,
            b.is_parlay,
            b.num_legs,
            '{config.CURRENCY}' AS currency,
            b.stake,
            b.placed_ts,
            b.settled_ts,
            CASE WHEN b.is_void THEN 'void'
                 WHEN a.n_loss > 0 THEN 'loss'
                 WHEN a.n_win = 0 THEN 'push'
                 ELSE 'win' END AS bet_outcome,
            ROUND(
                CASE WHEN b.is_void THEN b.stake
                     WHEN a.n_loss > 0 THEN 0
                     WHEN a.n_win = 0 THEN b.stake
                     ELSE b.stake * EXP(a.ln_win_odds_sum) END
            , 2) AS payout,
            ROUND(1 - EXP(a.struct_ln_sum), 6) AS structural_hold
        FROM stg_bets2 b
        JOIN _leg_agg a USING (bet_id)
    """)
    con.execute("DROP TABLE _leg_agg")
    con.execute("DROP TABLE stg_bets2")

    n_legs = con.execute("SELECT COUNT(*) FROM fact_bet_legs").fetchone()[0]
    n_settlements = con.execute("SELECT COUNT(*) FROM fact_settlements").fetchone()[0]
    elapsed = time.perf_counter() - t0

    return {
        "n_bets_requested": n_bets,
        "n_legs": n_legs,
        "n_settlements": n_settlements,
        "elapsed_seconds": round(elapsed, 2),
        "target_legs": target_legs,
    }


def export_parquet(con: duckdb.DuckDBPyConnection) -> None:
    """Write both fact tables to partitioned parquet under data/raw/."""
    config.ensure_dirs()
    legs_dir = config.RAW_DIR / "fact_bet_legs"
    settle_dir = config.RAW_DIR / "fact_settlements"
    con.execute(f"""
        COPY fact_bet_legs TO '{legs_dir.as_posix()}'
        (FORMAT PARQUET, PARTITION_BY (state, product), OVERWRITE_OR_IGNORE 1)
    """)
    con.execute(f"""
        COPY fact_settlements TO '{settle_dir.as_posix()}'
        (FORMAT PARQUET, PARTITION_BY (state, product), OVERWRITE_OR_IGNORE 1)
    """)


if __name__ == "__main__":
    con = duckdb.connect(str(config.MART_DB_PATH))
    stats = generate(con)
    print(stats)
    export_parquet(con)
    con.close()
