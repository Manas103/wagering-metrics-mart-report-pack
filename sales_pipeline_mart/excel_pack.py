"""Writes the pivot-ready Excel workbook: mart_metrics as a real Excel
Table (ListObject), a summary sheet, and the AI commentary verification
result, one row per sentence with its blocked/published status, using
openpyxl only. Same technique as wagering_mart/excel_pack.py.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


def write_workbook(
    con: duckdb.DuckDBPyConnection,
    out_path: Path,
    commentary_checks: list | None = None,
    mart_table: str = "mart_metrics",
) -> Path:
    out_path = Path(out_path)
    df = con.execute(f"SELECT * FROM {mart_table} ORDER BY year_month, region, product, segment").df()

    wb = Workbook()
    ws = wb.active
    ws.title = "mart_metrics"
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append(list(row))

    n_rows = len(df) + 1
    n_cols = len(df.columns)
    table = Table(displayName="MartMetrics", ref=f"A1:{get_column_letter(n_cols)}{n_rows}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
    ws.add_table(table)
    for col_idx, col_name in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(col_name) + 2)

    totals_row = con.execute(f"""
        SELECT
            COUNT(*) AS slices, ROUND(SUM(bookings), 2) AS bookings,
            SUM(won_count) AS won_count, SUM(lost_count) AS lost_count,
            ROUND(SUM(won_count) / NULLIF(SUM(won_count) + SUM(lost_count), 0), 6) AS win_rate,
            ROUND(SUM(open_pipeline), 2) AS open_pipeline
        FROM {mart_table}
    """).fetchone()

    ws2 = wb.create_sheet("summary")
    ws2.append(["metric", "value"])
    labels = ["slices (year_month x region x product x segment)", "total bookings ($)",
              "total won", "total lost", "win rate (blended)", "total open pipeline ($)"]
    for label, value in zip(labels, totals_row):
        ws2.append([label, value])
    ws2.column_dimensions["A"].width = 42
    ws2.column_dimensions["B"].width = 20

    if commentary_checks:
        ws3 = wb.create_sheet("ai_commentary")
        ws3.append(["sentence", "metric", "blocked", "reason"])
        for c in commentary_checks:
            ws3.append([c.sentence, c.metric, c.blocked, c.reason])
        ws3.column_dimensions["A"].width = 90
        ws3.column_dimensions["D"].width = 60

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
