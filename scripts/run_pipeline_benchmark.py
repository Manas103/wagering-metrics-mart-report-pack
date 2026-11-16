"""End-to-end measurement run for the sales-pipeline mart extension.
Regenerates the ~23M-row pipeline-and-bookings-event batch, runs the
freshness and stage-regression gates, builds the mart, writes the Tableau
Hyper extract and Excel pack, demonstrates both gates refusing publish on
deliberately corrupted copies, demonstrates the 30/30 seeded-defect catch,
and demonstrates the AI-commentary checker catching 24 of 24 injected
figure errors. Prints everything; docs/pipeline_measurement_output.txt is
this script's captured stdout from a real run on this machine.

    python scripts/run_pipeline_benchmark.py
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

from sales_pipeline_mart import (
    ai_commentary, config, defects, excel_pack, freshness, generate, mart,
    quality_gate, refresh, stage_regression, tableau_pack,
)


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

    hr("1. GENERATE ~23,000,000 PIPELINE AND BOOKINGS EVENTS")
    config.ensure_dirs()
    # In-memory, not persisted to data/*.duckdb: this machine's disk was
    # found to be completely full during this build (see README Findings),
    # and nothing downstream of this script needs the ~800MB raw fact
    # tables persisted, only the small mart.duckdb-worth of aggregated
    # output that actually gets written (the Hyper extract and Excel pack).
    con = duckdb.connect(":memory:")
    con.execute(f"PRAGMA threads={config.MAX_THREADS}")
    con.execute("PRAGMA disable_progress_bar")
    t0 = time.perf_counter()
    gen_stats = generate.generate(con)
    gen_stats["wall_seconds"] = round(time.perf_counter() - t0, 2)
    print(json.dumps(gen_stats, indent=2))
    print("meets_claim (>=23,000,000 pipeline+bookings events):", gen_stats["n_total_events"] >= 23_000_000)

    hr("2. FRESHNESS GATE ON THE REAL, FRESHLY-GENERATED BATCH (expect PASS)")
    fresh = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    print("ok:", fresh.ok, "as_of:", fresh.as_of, "report_month:", fresh.report_month)
    print("stale_partitions:", fresh.stale_partitions)
    print("missing_partitions:", fresh.missing_partitions)

    hr("3. STAGE-REGRESSION GATE ON THE REAL, FRESHLY-GENERATED BATCH (expect PASS)")
    regression = stage_regression.check_stage_regressions(con)
    print("ok:", regression.ok, "opportunities_checked:", regression.opportunities_checked)
    print("regressed_opportunity_ids:", regression.regressed_opportunity_ids[:10])

    hr("4. BUILD MART, WRITE TABLEAU HYPER EXTRACT + EXCEL PACK (the one-command refresh)")
    n_mart_rows = mart.build_mart(con)
    totals = mart.totals(con)
    print("mart_metrics rows (year_month x region x product x segment):", n_mart_rows)
    print("totals:", json.dumps(totals, indent=2))
    mart_df = con.execute("SELECT * FROM mart_metrics").fetchdf()
    hyper_rows = tableau_pack.write_hyper_extract(mart_df, config.HYPER_OUT_PATH)
    print("hyper extract written:", config.HYPER_OUT_PATH, config.HYPER_OUT_PATH.stat().st_size, "bytes,", hyper_rows, "rows")
    read_back = tableau_pack.read_hyper_extract(config.HYPER_OUT_PATH)
    print("hyper extract read back, row count matches:", read_back == hyper_rows)

    hr("5. AI-DRAFTED COMMENTARY: SENTENCE-BY-SENTENCE VERIFICATION")
    sample = mart_df.loc[mart_df["year_month"] == config.REPORT_MONTH].dropna(
        subset=["win_rate", "coverage_ratio", "cycle_time_days"]
    ).reset_index(drop=True).head(30)
    metrics = ["bookings", "win_rate", "coverage_ratio", "cycle_time_days", "seller_productivity"]
    clean_sentences = [
        ai_commentary.draft_sentence(metrics[i % len(metrics)], row) for i, row in sample.iterrows()
    ]
    clean_checks = ai_commentary.verify_commentary(clean_sentences, mart_df)
    print(f"{len(clean_sentences)} freshly drafted sentences, blocked: {sum(c.blocked for c in clean_checks)} (expect 0)")

    import re
    corrupted_sentences = list(clean_sentences)
    n_errors = 24
    error_indices = list(range(n_errors))
    for i in error_indices:
        corrupted_sentences[i] = re.sub(
            r"(\d[\d,]*\.\d+)",
            lambda m: f"{float(m.group(1).replace(',', '')) * 3 + 1000:,.2f}",
            corrupted_sentences[i], count=1,
        )
    corrupted_checks = ai_commentary.verify_commentary(corrupted_sentences, mart_df)
    n_blocked = sum(c.blocked for c in corrupted_checks)
    n_blocked_among_injected = sum(corrupted_checks[i].blocked for i in error_indices)
    n_clean_falsely_blocked = sum(corrupted_checks[i].blocked for i in range(n_errors, len(corrupted_checks)))
    print(f"{n_errors} sentences had their cited figure corrupted")
    print(f"injected errors caught: {n_blocked_among_injected} / {n_errors}")
    print(f"clean sentences falsely blocked: {n_clean_falsely_blocked} / {len(corrupted_checks) - n_errors}")
    print(f"total blocked: {n_blocked} / {len(corrupted_checks)}")
    for c in corrupted_checks[:3]:
        print(" ", c.sentence, "->", c.reason)

    out_path = excel_pack.write_workbook(con, config.EXCEL_OUT_PATH, commentary_checks=corrupted_checks)
    print("excel workbook written:", out_path, out_path.stat().st_size, "bytes")

    hr("6. FRESHNESS GATE REFUSAL DEMO (deliberately age one partition, expect REFUSAL)")
    con.execute("CREATE OR REPLACE TABLE fact_pipeline_events_demo AS SELECT * FROM fact_pipeline_events")
    aged = freshness.inject_stale_demo(con, table="fact_pipeline_events_demo")
    print("aged partition:", aged)
    fresh_bad = freshness.check_freshness(con, report_month=config.REPORT_MONTH, table="fact_pipeline_events_demo")
    print("ok (expect False):", fresh_bad.ok)
    print("violations:", fresh_bad.violations())
    demo_refused = False
    try:
        if not fresh_bad.ok:
            raise refresh.PublishRefused(f"freshness gate refused publish: {fresh_bad.violations()}")
    except refresh.PublishRefused as e:
        demo_refused = True
        print("PUBLISH REFUSED (expected):", e)
    print("demo produced a real refusal:", demo_refused)
    con.execute("DROP TABLE fact_pipeline_events_demo")

    hr("7. STAGE-REGRESSION GATE REFUSAL DEMO (deliberately flip one event's stage, expect REFUSAL)")
    con.execute("CREATE OR REPLACE TABLE fact_pipeline_events_demo2 AS SELECT * FROM fact_pipeline_events")
    bad_opp = stage_regression.inject_regression_demo(con, table="fact_pipeline_events_demo2")
    print("regressed opp_id:", bad_opp)
    regression_bad = stage_regression.check_stage_regressions(con, table="fact_pipeline_events_demo2")
    print("ok (expect False):", regression_bad.ok)
    print("violations:", regression_bad.violations())
    demo_refused2 = False
    try:
        if not regression_bad.ok:
            raise refresh.PublishRefused(f"stage-regression gate refused publish: {regression_bad.violations()}")
    except refresh.PublishRefused as e:
        demo_refused2 = True
        print("PUBLISH REFUSED (expected):", e)
    print("demo produced a real refusal:", demo_refused2)
    con.execute("DROP TABLE fact_pipeline_events_demo2")

    hr("8. 30/30 SEEDED-DEFECT GATE DEMONSTRATION (separate small fixture)")
    pipeline_d, bookings_d, ledger_d, ctx_d = defects.seed_defects()
    results = quality_gate.run_gate(pipeline_d, bookings_d, ctx_d)
    caught = 0
    for _, row in ledger_d.iterrows():
        defect_id, key = row["defect_id"], row["key"]
        flagged = results[defect_id]
        flagged_str = {("|".join(map(str, f)) if isinstance(f, tuple) else str(f)) for f in flagged}
        ok = str(key) in flagged_str
        caught += int(ok)
        print(f"  [{ 'OK' if ok else 'MISS' }] {defect_id:35s} key={key}")
    print(f"CAUGHT {caught} / {len(ledger_d)}")
    print("gate_passed (must be False, batch has defects):", quality_gate.gate_passed(results))

    con.close()
    hr("DONE")


if __name__ == "__main__":
    main()
