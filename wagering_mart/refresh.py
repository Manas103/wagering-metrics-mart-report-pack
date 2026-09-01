"""The one command that refreshes the mart, the Excel pack, and the data
the dashboard reads, behind a publish gate that can refuse to publish.

    python -m wagering_mart.refresh                 normal refresh
    python -m wagering_mart.refresh --generate       (re)generate the 25M-row batch first
    python -m wagering_mart.refresh --inject-stale-demo   demonstrate refusal on real data

Exit code is nonzero, and no mart/Excel output is written or updated, if
the freshness gate fails. This is enforced by raising PublishRefused and
letting it propagate; nothing downstream of the gate runs in that branch.
"""
from __future__ import annotations

import argparse
import sys
import time

import duckdb

from . import config, excel_pack, freshness, generate, mart


class PublishRefused(RuntimeError):
    pass


def run(
    do_generate: bool = False,
    inject_stale_demo: bool = False,
    target_legs: int = config.TARGET_LEG_COUNT,
    db_path=None,
    excel_path=None,
) -> dict:
    config.ensure_dirs()
    db_path = db_path or config.MART_DB_PATH
    excel_path = excel_path or config.EXCEL_OUT_PATH
    con = duckdb.connect(str(db_path))
    con.execute(f"PRAGMA threads={config.MAX_THREADS}")

    report = {"steps": []}

    if do_generate:
        t0 = time.perf_counter()
        gen_stats = generate.generate(con, target_legs=target_legs)
        gen_stats["elapsed_seconds_total"] = round(time.perf_counter() - t0, 2)
        report["generation"] = gen_stats
        report["steps"].append("generate")

    n_settlements = con.execute("SELECT COUNT(*) FROM fact_settlements").fetchone()[0]
    if n_settlements == 0:
        con.close()
        raise PublishRefused("no fact_settlements present; run with --generate first")

    aged_partition = None
    if inject_stale_demo:
        aged_partition = freshness.inject_stale_demo(con)
        report["inject_stale_demo"] = aged_partition

    fresh = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    report["freshness"] = {
        "ok": fresh.ok,
        "as_of": fresh.as_of,
        "report_month": fresh.report_month,
        "stale_partitions": fresh.stale_partitions,
        "missing_partitions": fresh.missing_partitions,
    }
    report["steps"].append("freshness_gate")

    if not fresh.ok:
        con.close()
        raise PublishRefused(
            f"freshness gate refused publish: "
            f"{len(fresh.stale_partitions)} stale, {len(fresh.missing_partitions)} missing "
            f"partitions for {config.REPORT_MONTH}. Violations: {fresh.violations()[:10]}"
        )

    n_mart_rows = mart.build_mart(con)
    report["mart_rows"] = n_mart_rows
    report["totals"] = mart.totals(con)
    report["steps"].append("build_mart")

    out_path = excel_pack.write_workbook(con, excel_path)
    report["excel_path"] = str(out_path)
    report["steps"].append("write_excel")

    con.close()
    report["published"] = True
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the wagering metrics mart and report pack.")
    parser.add_argument("--generate", action="store_true", help="(re)generate the synthetic batch first")
    parser.add_argument("--target-legs", type=int, default=config.TARGET_LEG_COUNT)
    parser.add_argument("--inject-stale-demo", action="store_true",
                         help="deliberately age one partition to demonstrate the freshness gate refusing publish")
    args = parser.parse_args(argv)

    try:
        report = run(
            do_generate=args.generate,
            inject_stale_demo=args.inject_stale_demo,
            target_legs=args.target_legs,
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
