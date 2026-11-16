"""The one command that refreshes the sales-pipeline mart, the Tableau
extract and the Excel pack, behind a publish gate that can refuse to
publish on a failed freshness or stage-regression check.

    python -m sales_pipeline_mart.refresh                  normal refresh
    python -m sales_pipeline_mart.refresh --generate        (re)generate the batch first
    python -m sales_pipeline_mart.refresh --inject-stale-demo       demonstrate freshness refusal
    python -m sales_pipeline_mart.refresh --inject-regression-demo  demonstrate stage-regression refusal

Exit code is nonzero, and no mart/Tableau/Excel output is written, if
either gate fails, the same PublishRefused pattern wagering_mart/refresh.py
uses.
"""
from __future__ import annotations

import argparse
import sys
import time

import duckdb

from . import ai_commentary, config, excel_pack, freshness, generate, mart, stage_regression, tableau_pack


class PublishRefused(RuntimeError):
    pass


def _draft_and_verify_commentary(con: duckdb.DuckDBPyConnection) -> list:
    mart_df = con.execute("SELECT * FROM mart_metrics").fetchdf()
    sample = mart_df.loc[mart_df["year_month"] == config.REPORT_MONTH].dropna(subset=["win_rate"]).head(10)
    metrics = ["bookings", "win_rate", "coverage_ratio", "cycle_time_days", "seller_productivity"]
    sentences = [
        ai_commentary.draft_sentence(metrics[i % len(metrics)], row)
        for i, (_, row) in enumerate(sample.iterrows())
    ]
    return ai_commentary.verify_commentary(sentences, mart_df)


def run(
    do_generate: bool = False,
    inject_stale_demo: bool = False,
    inject_regression_demo: bool = False,
    n_opportunities: int = config.N_OPPORTUNITIES,
    db_path=None,
    excel_path=None,
    hyper_path=None,
) -> dict:
    config.ensure_dirs()
    # Defaults to in-memory, not data/sales_pipeline_mart.duckdb: this
    # machine's disk was found to be completely full during this build
    # (see README Findings); the raw fact tables (~800MB at full scale)
    # do not need to be persisted, only the small aggregated outputs
    # (Hyper extract, Excel pack) actually written below. Pass an explicit
    # db_path to persist the raw tables when disk space allows.
    excel_path = excel_path or config.EXCEL_OUT_PATH
    hyper_path = hyper_path or config.HYPER_OUT_PATH
    con = duckdb.connect(str(db_path) if db_path else ":memory:")
    con.execute(f"PRAGMA threads={config.MAX_THREADS}")
    con.execute("PRAGMA disable_progress_bar")

    report: dict = {"steps": []}

    if do_generate:
        t0 = time.perf_counter()
        gen_stats = generate.generate(con, n_opportunities=n_opportunities)
        gen_stats["elapsed_seconds_total"] = round(time.perf_counter() - t0, 2)
        report["generation"] = gen_stats
        report["steps"].append("generate")

    n_events = con.execute("SELECT COUNT(*) FROM fact_pipeline_events").fetchone()[0]
    if n_events == 0:
        con.close()
        raise PublishRefused("no fact_pipeline_events present; run with --generate first")

    if inject_stale_demo:
        report["inject_stale_demo"] = freshness.inject_stale_demo(con)
    if inject_regression_demo:
        report["inject_regression_demo"] = stage_regression.inject_regression_demo(con)

    fresh = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    report["freshness"] = {
        "ok": fresh.ok, "as_of": fresh.as_of, "report_month": fresh.report_month,
        "stale_partitions": fresh.stale_partitions, "missing_partitions": fresh.missing_partitions,
    }
    report["steps"].append("freshness_gate")
    if not fresh.ok:
        con.close()
        raise PublishRefused(
            f"freshness gate refused publish: {len(fresh.stale_partitions)} stale, "
            f"{len(fresh.missing_partitions)} missing partitions for {config.REPORT_MONTH}. "
            f"Violations: {fresh.violations()[:10]}"
        )

    regression = stage_regression.check_stage_regressions(con)
    report["stage_regression"] = {
        "ok": regression.ok, "opportunities_checked": regression.opportunities_checked,
        "regressed_opportunity_ids": regression.regressed_opportunity_ids[:10],
    }
    report["steps"].append("stage_regression_gate")
    if not regression.ok:
        con.close()
        raise PublishRefused(
            f"stage-regression gate refused publish: {len(regression.regressed_opportunity_ids)} "
            f"opportunities with a stage that moved backward. Violations: {regression.violations()[:10]}"
        )

    n_mart_rows = mart.build_mart(con)
    report["mart_rows"] = n_mart_rows
    report["totals"] = mart.totals(con)
    report["steps"].append("build_mart")

    commentary_checks = _draft_and_verify_commentary(con)
    report["ai_commentary"] = {
        "n_sentences": len(commentary_checks),
        "n_blocked": sum(c.blocked for c in commentary_checks),
        "n_published": sum(not c.blocked for c in commentary_checks),
    }
    report["steps"].append("ai_commentary_check")

    hyper_rows = tableau_pack.write_hyper_extract(
        con.execute("SELECT * FROM mart_metrics").fetchdf(), hyper_path
    )
    report["hyper_path"] = str(hyper_path)
    report["hyper_rows"] = hyper_rows
    report["steps"].append("write_hyper_extract")

    out_path = excel_pack.write_workbook(con, excel_path, commentary_checks=commentary_checks)
    report["excel_path"] = str(out_path)
    report["steps"].append("write_excel")

    con.close()
    report["published"] = True
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the sales-pipeline mart, Tableau extract and Excel pack.")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--n-opportunities", type=int, default=config.N_OPPORTUNITIES)
    parser.add_argument("--inject-stale-demo", action="store_true")
    parser.add_argument("--inject-regression-demo", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run(
            do_generate=args.generate,
            inject_stale_demo=args.inject_stale_demo,
            inject_regression_demo=args.inject_regression_demo,
            n_opportunities=args.n_opportunities,
        )
    except PublishRefused as e:
        print(f"PUBLISH REFUSED: {e}", file=sys.stderr)
        return 1

    print("PUBLISHED OK")
    for k, v in report.items():
        if k != "steps":
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
