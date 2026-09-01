"""Writes the pivot-ready Excel workbook: mart_metrics as a real Excel
Table (ListObject), plus a small Summary sheet, using openpyxl only (no
Excel installation required to produce or read it).

A genuine Table object (not just a formatted range) is what lets a user
drop a PivotTable on top of the sheet and have Excel treat it as a
structured data source with named columns and auto-expanding rows.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter


def write_workbook(con: duckdb.DuckDBPyConnection, out_path: Path, mart_table: str = "mart_metrics") -> Path:
    df = con.execute(f"SELECT * FROM {mart_table} ORDER BY year_month, state, product").df()

    wb = Workbook()
    ws = wb.active
    ws.title = "mart_metrics"

    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append(list(row))

    n_rows = len(df) + 1
    n_cols = len(df.columns)
    last_col_letter = get_column_letter(n_cols)
    table_ref = f"A1:{last_col_letter}{n_rows}"
    table = Table(displayName="MartMetrics", ref=table_ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False
    )
    ws.add_table(table)
    for col_idx, col_name in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(col_name) + 2)

    totals_row = con.execute(f"""
        SELECT
            COUNT(*) AS bet_count_rows,
            SUM(bet_count) AS bet_count,
            ROUND(SUM(handle), 2) AS handle,
            ROUND(SUM(payout), 2) AS payout,
            ROUND(SUM(net_revenue), 2) AS net_revenue,
            ROUND(SUM(net_revenue) / NULLIF(SUM(handle), 0), 6) AS actual_hold,
            ROUND(SUM(handle * structural_hold) / NULLIF(SUM(handle), 0), 6) AS structural_hold,
            ROUND(SUM(parlay_handle) / NULLIF(SUM(handle), 0), 6) AS parlay_mix
        FROM {mart_table}
    """).fetchone()

    ws2 = wb.create_sheet("summary")
    ws2.append(["metric", "value"])
    labels = [
        "slices (year_month x state x product)", "total bets", "total handle ($)",
        "total payout ($)", "total net revenue ($)", "actual hold (blended)",
        "structural hold (blended, handle-weighted)", "parlay mix (handle share)",
    ]
    for label, value in zip(labels, totals_row):
        ws2.append([label, value])
    ws2.column_dimensions["A"].width = 42
    ws2.column_dimensions["B"].width = 20

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
