"""Optional live-PostgreSQL path. Checks reachability, loads the DDL, and
mirrors mart_metrics (and, on request, the raw fact tables) into a real
Postgres instance when one is reachable. Never required: refresh.py works
entirely on DuckDB if Postgres is not reachable, and says so.
"""
from __future__ import annotations

from pathlib import Path

from . import config

SCHEMA_PATH = config.REPO_ROOT / "sql" / "schema_postgres.sql"


def is_postgres_reachable(dsn: str = config.PG_DSN, timeout: int = 3) -> bool:
    try:
        import psycopg2
    except ImportError:
        return False
    try:
        conn = psycopg2.connect(dsn, connect_timeout=timeout)
        conn.close()
        return True
    except Exception:
        return False


def apply_schema(dsn: str = config.PG_DSN) -> None:
    import psycopg2

    ddl = SCHEMA_PATH.read_text()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def load_mart_metrics(df, dsn: str = config.PG_DSN) -> int:
    """Replaces the mart_metrics table contents with `df` (a pandas
    DataFrame shaped like wagering_mart.mart.MART_SQL's output) using a
    real INSERT, for genuine end-to-end verification against Postgres."""
    import psycopg2
    from psycopg2.extras import execute_values

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE mart_metrics")
            cols = list(df.columns)
            values = [tuple(row) for row in df.itertuples(index=False)]
            execute_values(
                cur,
                f"INSERT INTO mart_metrics ({', '.join(cols)}) VALUES %s",
                values,
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM mart_metrics")
            n = cur.fetchone()[0]
        return n
    finally:
        conn.close()
