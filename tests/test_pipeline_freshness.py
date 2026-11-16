"""Freshness gate tests for the sales-pipeline extension: it passes a
fresh batch, and it genuinely refuses (PublishRefused) a batch with an
aged partition, run against real DuckDB tables. Same precedent as
tests/test_freshness.py for the wagering mart: the fixture needs to be
large enough that even the rarest (region, product, segment) slice has an
event within the staleness budget of the report month's end, or the
"fresh batch passes" test is flaky by chance, not by a gate defect.
"""
from __future__ import annotations

import duckdb
import pytest

from sales_pipeline_mart import config, freshness, generate, refresh

N_OPPORTUNITIES = 60_000  # large enough that every one of the 72
                          # (region, product, segment) slices has recent
                          # activity; see module docstring


def _fresh_con():
    con = duckdb.connect()
    generate.generate(con, n_opportunities=N_OPPORTUNITIES)
    return con


def test_freshness_passes_on_freshly_generated_batch():
    con = _fresh_con()
    result = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    assert result.ok, result.violations()
    con.close()


def test_freshness_flags_missing_partitions():
    con = _fresh_con()
    con.execute("DELETE FROM fact_pipeline_events WHERE region = 'NA' AND product = 'Video' AND segment = 'SMB'")
    result = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    assert not result.ok
    assert ("NA", "Video", "SMB") in result.missing_partitions
    con.close()


def test_freshness_flags_stale_partition():
    con = _fresh_con()
    aged = freshness.inject_stale_demo(con)
    result = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    assert not result.ok
    assert tuple(aged.split("|")) in result.stale_partitions
    con.close()


def test_refresh_run_refuses_publish_when_stale(tmp_path):
    # This test needs a file-backed connection (unlike the other tests in
    # this module): it calls refresh.run() twice and the second call
    # (do_generate=False) must see the first call's generated data, which
    # only a persisted database makes possible. At this fixture's scale
    # (60,000 opportunities) the file is tens of MB, not the ~800MB a full
    # ~645,000-opportunity run would write; see the in-memory default in
    # refresh.run() and README Findings for why that default exists.
    db_path = tmp_path / "t.duckdb"
    report = refresh.run(
        do_generate=True, n_opportunities=N_OPPORTUNITIES, db_path=db_path,
        excel_path=tmp_path / "t.xlsx", hyper_path=tmp_path / "t.hyper",
    )
    assert report["published"] is True

    with pytest.raises(refresh.PublishRefused):
        refresh.run(
            do_generate=False, inject_stale_demo=True, db_path=db_path,
            excel_path=tmp_path / "t.xlsx", hyper_path=tmp_path / "t.hyper",
        )


def test_refresh_run_publishes_when_fresh(tmp_path):
    report = refresh.run(
        do_generate=True, n_opportunities=N_OPPORTUNITIES,
        excel_path=tmp_path / "t2.xlsx", hyper_path=tmp_path / "t2.hyper",
    )
    assert report["published"] is True
    assert report["freshness"]["ok"] is True
    assert report["stage_regression"]["ok"] is True
    assert report["mart_rows"] > 0
    assert report["excel_path"]
    assert report["hyper_rows"] > 0
