"""Fixed simulation universe for the sales-pipeline extension, kept
separate from wagering_mart/config.py because the two simulated worlds
(sportsbook wagering, advertiser sales pipeline) share no parameters, only
the generation and report-pack techniques.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PIPELINE_DB_PATH = DATA_DIR / "sales_pipeline_mart.duckdb"
EXCEL_OUT_PATH = DATA_DIR / "sales_pipeline_report_pack.xlsx"
HYPER_OUT_PATH = DATA_DIR / "sales_pipeline_mart.hyper"
SAMPLE_EXCEL_PATH = REPO_ROOT / "docs" / "sample_pipeline_report_pack.xlsx"
SAMPLE_HYPER_PATH = REPO_ROOT / "docs" / "sample_pipeline_mart.hyper"

REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
REGION_WEIGHTS = {"NA": 0.42, "EMEA": 0.27, "APAC": 0.21, "LATAM": 0.10}

PRODUCTS = ["Standard Display", "Video", "Shopping", "Idea Ads", "Premiere Spotlight", "Performance Plus"]
PRODUCT_WEIGHTS = {
    "Standard Display": 0.22, "Video": 0.18, "Shopping": 0.20,
    "Idea Ads": 0.14, "Premiere Spotlight": 0.08, "Performance Plus": 0.18,
}

SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
SEGMENT_WEIGHTS = {"Enterprise": 0.15, "Mid-Market": 0.33, "SMB": 0.52}

N_OPPORTUNITIES = 645_000
N_REPS = 260

STAGES = {1: "Prospecting", 2: "Qualification", 3: "Proposal", 4: "Negotiation"}
# Typical total days open (sum across all 4 stages) by segment, before the
# per-opportunity speed_factor is applied.
SEGMENT_TYPICAL_CYCLE_DAYS = {"Enterprise": 70, "Mid-Market": 42, "SMB": 21}
SPEED_FACTOR_SIGMA = 0.28

SEGMENT_BASE_WIN_RATE = {"Enterprise": 0.34, "Mid-Market": 0.29, "SMB": 0.24}
AMOUNT_SCALE = {"Enterprise": 48_000.0, "Mid-Market": 14_000.0, "SMB": 3_800.0}

# Report window: 22 full months ending before "today" (2026-11-16), so the
# synthetic activity is never dated in the future.
REPORT_WINDOW_START = "2025-01-01"
REPORT_WINDOW_END_EXCLUSIVE = "2026-11-01"
REPORT_MONTH = "2026-10"

# Freshness gate: the latest event in every (region, product, segment)
# partition for REPORT_MONTH must be within this many days of the as-of
# time used for the run (coarser than the wagering mart's 24-hour window,
# because pipeline events are logged daily, not in real time).
FRESHNESS_MAX_STALENESS_DAYS = 2

RNG_SEED = 20261016

# Cap on DuckDB threads, per the house rule of never using more than half
# the logical cores on this machine (16 logical cores total -> cap at 8).
MAX_THREADS = 8


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "docs").mkdir(parents=True, exist_ok=True)
