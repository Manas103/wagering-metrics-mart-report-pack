"""The stage-regression gate: passes on a clean batch, genuinely refuses
on a batch with one opportunity's stage deliberately flipped backward.
"""
from __future__ import annotations

import duckdb

from sales_pipeline_mart import stage_regression, generate


def _con(n=20_000):
    con = duckdb.connect()
    generate.generate(con, n_opportunities=n)
    return con


def test_passes_on_clean_batch():
    con = _con()
    result = stage_regression.check_stage_regressions(con)
    assert result.ok
    assert result.regressed_opportunity_ids == []
    assert result.opportunities_checked > 0
    con.close()


def test_flags_a_deliberately_regressed_opportunity():
    con = _con()
    bad_opp = stage_regression.inject_regression_demo(con)
    result = stage_regression.check_stage_regressions(con)
    assert not result.ok
    assert bad_opp in result.regressed_opportunity_ids
    con.close()


def test_violations_format_includes_opp_id():
    con = _con()
    bad_opp = stage_regression.inject_regression_demo(con)
    result = stage_regression.check_stage_regressions(con)
    assert any(str(bad_opp) in v for v in result.violations())
    con.close()
