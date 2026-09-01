"""Fixed reference data and paths shared by every module.

Nothing in here is derived from a live source; it is the fixed universe
the synthetic generator draws from, kept in one place so the generator,
the metrics layer and the quality gate agree on what a valid state or
product looks like.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # generated bet legs / settlements (parquet), gitignored
MART_DB_PATH = DATA_DIR / "mart.duckdb"
EXCEL_OUT_PATH = DATA_DIR / "wagering_report_pack.xlsx"
SAMPLE_EXCEL_PATH = REPO_ROOT / "docs" / "sample_report_pack.xlsx"

# ---------------------------------------------------------------------------
# States: 13 states where DK-style mobile sports betting is live, used only
# as a realistic, fixed simulation universe (not sourced from any live feed).
# ---------------------------------------------------------------------------
STATES = [
    "NJ", "PA", "NY", "IL", "MI", "CO", "VA", "AZ", "TN", "IN", "LA", "OH", "MA",
]

# Relative handle weight per state (bigger states get more simulated volume).
STATE_WEIGHTS = {
    "NJ": 1.0, "PA": 1.1, "NY": 1.6, "IL": 1.2, "MI": 0.9, "CO": 0.6,
    "VA": 0.7, "AZ": 0.7, "TN": 0.6, "IN": 0.6, "LA": 0.5, "OH": 1.0, "MA": 0.8,
}

# ---------------------------------------------------------------------------
# Products: 11 straight-bet sports/casino products plus "Same Game Parlay",
# which is reported as its own product the way a real sportsbook BI team
# reports parlay handle as a distinct line, not just a bet-type flag.
# ---------------------------------------------------------------------------
STRAIGHT_PRODUCTS = [
    "NFL", "NBA", "MLB", "NHL", "NCAAF", "NCAAB",
    "Soccer", "Tennis", "MMA", "Golf", "Casino",
]
PARLAY_PRODUCT = "Same Game Parlay"
PRODUCTS = STRAIGHT_PRODUCTS + [PARLAY_PRODUCT]

STRAIGHT_PRODUCT_WEIGHTS = {
    "NFL": 2.2, "NBA": 1.6, "MLB": 1.3, "NHL": 0.8, "NCAAF": 1.1, "NCAAB": 0.7,
    "Soccer": 0.9, "Tennis": 0.5, "MMA": 0.4, "Golf": 0.4, "Casino": 1.0,
}

# ---------------------------------------------------------------------------
# Generation parameters
# ---------------------------------------------------------------------------
TARGET_LEG_COUNT = 25_000_000
PARLAY_BET_SHARE = 0.22          # fraction of bets that are parlays
PARLAY_MIN_LEGS = 2
PARLAY_MAX_LEGS = 6
N_CUSTOMERS = 500_000
CURRENCY = "USD"

# Report window: six full months ending before "today" (2026-08-31), so the
# synthetic betting activity is itself never dated in the future.
REPORT_WINDOW_START = "2026-02-01"
REPORT_WINDOW_END_EXCLUSIVE = "2026-08-01"   # up to but not including Aug 2026
REPORT_MONTH = "2026-07"                      # the month the refresh publishes

# Freshness gate: every state x product partition for REPORT_MONTH must have
# a max placed_ts within this many hours of the as-of time used for the run.
FRESHNESS_MAX_STALENESS_HOURS = 24

# Random seed used for reproducible-shape (not bit-identical across thread
# counts) synthetic generation.
RNG_SEED = 20260731

# Cap on DuckDB threads / any parallel generation, per the house rule of
# never using more than half the logical cores on this machine (16 logical
# cores total -> cap at 8).
MAX_THREADS = 8


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "docs").mkdir(parents=True, exist_ok=True)


# PostgreSQL connection used when a live instance is reachable (see db.py).
PG_DSN = os.environ.get(
    "WAGERING_MART_PG_DSN",
    "postgresql://wagering_app:wagering_app_pw@localhost:5432/wagering_mart",
)
