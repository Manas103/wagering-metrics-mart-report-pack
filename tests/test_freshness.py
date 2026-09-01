"""Freshness gate tests: it passes a fresh batch, and it genuinely refuses
(nonzero-exit-equivalent, via PublishRefused) a batch with an aged
partition, run against real DuckDB tables, not mocked.
"""
from __future__ import annotations

import duckdb
import pytest

from wagering_mart import config, freshness, generate, refresh

N_LEGS = 2_500_000  # large enough that even the rarest (state, product)
                     # partition (a low-weight sport in a low-weight state)
                     # has a bet within the last 24h of the report month,
                     # so the "fresh batch passes" test isn't flaky by chance


def _fresh_con():
    con = duckdb.connect()
    generate.generate(con, target_legs=N_LEGS)
    return con


def test_freshness_passes_on_freshly_generated_batch():
    con = _fresh_con()
    result = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    # freshly generated data's max placed_ts for the report month is at or
    # near the window end, so it must be within the staleness budget of
    # itself-as-as-of-time.
    assert result.ok, result.violations()
    con.close()


def test_freshness_flags_missing_partitions():
    con = _fresh_con()
    con.execute("DELETE FROM fact_settlements WHERE state = 'NJ' AND product = 'NFL'")
    result = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    assert not result.ok
    assert ("NJ", "NFL") in result.missing_partitions
    con.close()


def test_freshness_flags_stale_partition():
    con = _fresh_con()
    aged = freshness.inject_stale_demo(con)
    result = freshness.check_freshness(con, report_month=config.REPORT_MONTH)
    assert not result.ok
    aged_tuple = tuple(aged.split("|"))
    assert aged_tuple in result.stale_partitions
    con.close()


def test_refresh_run_refuses_publish_when_stale(tmp_path):
    db_path = tmp_path / "t.duckdb"
    excel_path = tmp_path / "t.xlsx"
    report = refresh.run(do_generate=True, target_legs=N_LEGS, db_path=db_path, excel_path=excel_path)
    assert report["published"] is True

    with pytest.raises(refresh.PublishRefused):
        refresh.run(do_generate=False, inject_stale_demo=True, db_path=db_path, excel_path=excel_path)


def test_refresh_run_publishes_when_fresh(tmp_path):
    db_path = tmp_path / "t2.duckdb"
    excel_path = tmp_path / "t2.xlsx"
    report = refresh.run(do_generate=True, target_legs=N_LEGS, db_path=db_path, excel_path=excel_path)
    assert report["published"] is True
    assert report["freshness"]["ok"] is True
    assert report["mart_rows"] > 0
    assert report["excel_path"]
