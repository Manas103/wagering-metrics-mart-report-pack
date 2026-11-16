"""Writes mart_metrics to a real Tableau Hyper extract via the Tableau
Hyper API, the same object a packaged Tableau workbook (.twbx) would point
to as its data source. No Tableau Desktop or Server is installed on this
machine; the Hyper API runs its own embedded `hyperd` process (started and
stopped by the `with HyperProcess(...)` block below, never left running),
and writing a real `.hyper` file is a legitimate way to produce a Tableau
data source without one, the same way `excel_pack.py` produces a real
Excel workbook via openpyxl without Excel installed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
from tableauhyperapi import (
    Connection,
    CreateMode,
    HyperProcess,
    Inserter,
    SqlType,
    TableDefinition,
    TableName,
    Telemetry,
)

MART_TABLE_NAME = TableName("public", "mart_metrics")

_COLUMN_TYPES = [
    ("year_month", SqlType.text()),
    ("region", SqlType.text()),
    ("product", SqlType.text()),
    ("segment", SqlType.text()),
    ("bookings", SqlType.double()),
    ("won_count", SqlType.big_int()),
    ("lost_count", SqlType.big_int()),
    ("win_rate", SqlType.double()),
    ("cycle_time_days", SqlType.double()),
    ("active_reps", SqlType.big_int()),
    ("seller_productivity", SqlType.double()),
    ("open_pipeline", SqlType.double()),
    ("coverage_ratio", SqlType.double()),
]


def write_hyper_extract(mart_df: pd.DataFrame, path: str | Path) -> int:
    """Writes mart_df to a .hyper extract at `path`. Returns the row count
    written. hyperd's own logs are redirected to the system temp directory
    so a refresh never leaves log files inside the repository."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [TableDefinition.Column(name, sql_type) for name, sql_type in _COLUMN_TYPES]
    table_def = TableDefinition(table_name=MART_TABLE_NAME, columns=columns)

    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                       parameters={"log_dir": tempfile.gettempdir()}) as hyper:
        with Connection(endpoint=hyper.endpoint, database=str(path), create_mode=CreateMode.CREATE_AND_REPLACE) as con:
            con.catalog.create_table(table_def)
            int_columns = {"won_count", "lost_count", "active_reps"}
            col_names = [c[0] for c in _COLUMN_TYPES]
            with Inserter(con, table_def) as inserter:
                for row in mart_df[col_names].itertuples(index=False):
                    values = []
                    for name, v in zip(col_names, row):
                        if pd.isna(v):
                            values.append(None)
                        elif name in int_columns:
                            values.append(int(v))
                        else:
                            values.append(v)
                    inserter.add_row(values)
                inserter.execute()
            n = con.execute_scalar_query(f"SELECT COUNT(*) FROM {MART_TABLE_NAME}")
    return int(n)


def read_hyper_extract(path: str | Path) -> int:
    """Reads back the row count from a .hyper extract, used to verify a
    written file is actually a valid, queryable Hyper database."""
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                       parameters={"log_dir": tempfile.gettempdir()}) as hyper:
        with Connection(endpoint=hyper.endpoint, database=str(path)) as con:
            return int(con.execute_scalar_query(f"SELECT COUNT(*) FROM {MART_TABLE_NAME}"))
