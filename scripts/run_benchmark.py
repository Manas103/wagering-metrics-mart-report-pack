"""End-to-end measurement run. Regenerates the full ~25M-row batch, runs
the publish gate, builds the mart, writes the Excel pack, demonstrates the
freshness gate refusing publish on a deliberately staled copy, demonstrates
the 30/30 seeded-defect catch, and (if reachable) mirrors mart_metrics into
a live PostgreSQL instance. Prints everything; docs/measurement_output.txt
is this script's captured stdout from a real run on this machine.

    python scripts/run_benchmark.py
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from wagering_mart import config, db, defects, freshness, generate, mart, quality_gate, refresh


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main():
    hr("MACHINE")
    print("platform:", platform.platform())
    print("processor:", platform.processor())
    print("logical cores (os.cpu_count):", os.cpu_count())
    print("machine spec (stated): AMD Ryzen 7 7800X3D, 8 physical / 16 logical cores, Windows 11")
    print("python:", sys.version)

    hr("1. GENERATE ~25,000,000 BET LEGS (target %s)" % config.TARGET_LEG_COUNT)
    config.ensure_dirs()
    con = duckdb.connect(str(config.MART_DB_PATH))
    t0 = time.perf_counter()
    gen_stats = generate.generate(con, target_legs=config.TARGET_LEG_COUNT)
    gen_stats["wall_seconds"] = round(time.perf_counter() - t0, 2)
    print(json.dumps(gen_stats, indent=2))
    print("meets_claim (>=25,000,000 legs processed):", gen_stats["n_legs"] >= 25_000_000)

    hr("2. INVARIANT SPOT-CHECKS ON THE FULL BATCH")
    handle_raw = con.execute("SELECT ROUND(SUM(stake),2) FROM fact_settlements").fetchone()[0]
    n_bets = con.execute("SELECT COUNT(*) FROM fact_settlements").fetchone()[0]
    n_legs_check = con.execute("SELECT COUNT(*) FROM fact_bet_legs").fetchone()[0]
    mismatch = con.execute("""
        SELECT COUNT(*) FROM fact_settlements s
        JOIN (SELECT bet_id, COUNT(*) n FROM fact_bet_legs GROUP BY 1) l USING (bet_id)
        WHERE s.num_legs != l.n
    """).fetchone()[0]
    print("total bets (settlements):", n_bets)
    print("total legs:", n_legs_check)
    print("total handle ($):", handle_raw)
    print("num_legs vs actual leg-row-count mismatches (should be 0):", mismatch)

    hr("3. FRESHNESS GATE ON THE REAL, FRESHLY-GENERATED BATCH (expect PASS)")
    fresh = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    print("ok:", fresh.ok, "as_of:", fresh.as_of, "report_month:", fresh.report_month)
    print("stale_partitions:", fresh.stale_partitions)
    print("missing_partitions:", fresh.missing_partitions)

    hr("4. BUILD MART + WRITE EXCEL PACK (the one-command refresh)")
    n_mart_rows = mart.build_mart(con)
    totals = mart.totals(con)
    print("mart_metrics rows (year_month x state x product):", n_mart_rows)
    print("totals:", json.dumps(totals, indent=2))
    from wagering_mart import excel_pack
    out_path = excel_pack.write_workbook(con, config.EXCEL_OUT_PATH)
    print("excel workbook written:", out_path, out_path.stat().st_size, "bytes")

    hr("5. FRESHNESS GATE REFUSAL DEMO (deliberately age one partition, expect REFUSAL)")
    # Demonstrated on a full in-memory COPY of the real fact_settlements
    # table (not the original), so the refusal demo is genuine (real data,
    # real gate, real UPDATE) without disturbing the fresh batch the rest
    # of this run publishes from.
    con.execute("CREATE OR REPLACE TABLE fact_settlements_demo AS SELECT * FROM fact_settlements")
    aged = freshness.inject_stale_demo(con, table="fact_settlements_demo")
    print("aged partition:", aged)
    fresh_bad = freshness.check_freshness(con, report_month=config.REPORT_MONTH, table="fact_settlements_demo")
    print("ok (expect False):", fresh_bad.ok)
    print("violations:", fresh_bad.violations())
    demo_refused = False
    try:
        gate_check = freshness.check_freshness(con, report_month=config.REPORT_MONTH, table="fact_settlements_demo")
        if not gate_check.ok:
            raise refresh.PublishRefused(f"freshness gate refused publish: {gate_check.violations()}")
    except refresh.PublishRefused as e:
        demo_refused = True
        print("PUBLISH REFUSED (expected):", e)
    print("demo produced a real refusal:", demo_refused)
    con.execute("DROP TABLE fact_settlements_demo")

    hr("6. 30/30 SEEDED-DEFECT GATE DEMONSTRATION (separate small fixture)")
    legs_d, settle_d, ledger_d, ctx_d = defects.seed_defects()
    results = quality_gate.run_gate(legs_d, settle_d, ctx_d)
    caught = 0
    for _, row in ledger_d.iterrows():
        defect_id, key = row["defect_id"], row["key"]
        flagged = results[defect_id]
        flagged_str = {f"{s}|{p}" for s, p in flagged} if defect_id in ("missing_partition", "stale_partition") else {str(x) for x in flagged}
        ok = str(key) in flagged_str
        caught += int(ok)
        print(f"  [{ 'OK' if ok else 'MISS' }] {defect_id:35s} key={key}")
    print(f"CAUGHT {caught} / {len(ledger_d)}")
    print("gate_passed (must be False, batch has defects):", quality_gate.gate_passed(results))

    hr("7. LIVE POSTGRESQL CHECK")
    reachable = db.is_postgres_reachable()
    print("postgres reachable:", reachable, "dsn:", config.PG_DSN)
    if reachable:
        db.apply_schema()
        mart_df = con.execute("SELECT * FROM mart_metrics ORDER BY 1,2,3").df()
        n_loaded = db.load_mart_metrics(mart_df)
        print("rows loaded into live PostgreSQL mart_metrics:", n_loaded)

    hr("8. EXPORT PARTITIONED PARQUET (raw fact tables, gitignored)")
    t0 = time.perf_counter()
    generate.export_parquet(con)
    print("export elapsed seconds:", round(time.perf_counter() - t0, 2))

    con.close()
    hr("DONE")


if __name__ == "__main__":
    main()
