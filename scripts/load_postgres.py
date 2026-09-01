"""Loads the already-built mart_metrics table into a live PostgreSQL
instance. Run right after `sudo service postgresql start` in WSL2, since
the WSL2 VM (and Postgres with it) is torn down after a short idle period
with no active WSL process, and the main benchmark run is long enough that
Postgres can go unreachable partway through it.

    python scripts/load_postgres.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from wagering_mart import config, db


def main():
    reachable = db.is_postgres_reachable()
    print("postgres reachable:", reachable, "dsn:", config.PG_DSN)
    if not reachable:
        print("PostgreSQL not reachable, nothing loaded.")
        return 1

    con = duckdb.connect(str(config.MART_DB_PATH), read_only=True)
    mart_df = con.execute("SELECT * FROM mart_metrics ORDER BY 1, 2, 3").df()
    con.close()
    print("rows to load:", len(mart_df))

    db.apply_schema()
    print("DDL applied (CREATE TABLE IF NOT EXISTS ...)")
    n = db.load_mart_metrics(mart_df)
    print("rows now in live PostgreSQL mart_metrics:", n)

    import psycopg2
    conn = psycopg2.connect(config.PG_DSN)
    cur = conn.cursor()
    cur.execute("SELECT year_month, state, product, handle, actual_hold, structural_hold FROM mart_metrics ORDER BY handle DESC LIMIT 5")
    print("top 5 slices by handle, read back from PostgreSQL:")
    for row in cur.fetchall():
        print(" ", row)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
