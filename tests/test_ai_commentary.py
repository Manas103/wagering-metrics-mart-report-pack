"""The AI-commentary verifier: a freshly drafted sentence always verifies
clean against the row it was drafted from (reference check), and a
sentence whose cited figure is deliberately corrupted is always blocked,
independent of every other sentence.
"""
from __future__ import annotations

import pandas as pd

from sales_pipeline_mart import ai_commentary

ROW = pd.Series({
    "region": "NA", "product": "Video", "segment": "Enterprise", "year_month": "2026-10",
    "bookings": 1234567.89, "win_rate": 0.4123, "coverage_ratio": 7.5,
    "cycle_time_days": 62.3, "seller_productivity": 9876.54,
})

MART_DF = pd.DataFrame([ROW])


def test_each_template_drafts_a_sentence_that_verifies_clean():
    for metric in ["bookings", "win_rate", "coverage_ratio", "cycle_time_days", "seller_productivity"]:
        sentence = ai_commentary.draft_sentence(metric, ROW)
        check = ai_commentary.verify_sentence(sentence, MART_DF)
        assert not check.blocked, check.reason


def test_corrupted_figure_is_blocked():
    sentence = ai_commentary.draft_sentence("bookings", ROW)
    corrupted = sentence.replace("1,234,567.89", "9,999,999.99")
    check = ai_commentary.verify_sentence(corrupted, MART_DF)
    assert check.blocked
    assert "disagrees" in check.reason


def test_unparseable_sentence_is_blocked():
    check = ai_commentary.verify_sentence("Bookings were pretty good this quarter.", MART_DF)
    assert check.blocked
    assert check.metric is None


def test_sentence_for_unknown_slice_is_blocked():
    sentence = "Bookings in NA for Video (Enterprise) in 2099-01 totaled $1.00."
    check = ai_commentary.verify_sentence(sentence, MART_DF)
    assert check.blocked
    assert "no matching mart row" in check.reason


def test_small_rounding_difference_is_tolerated():
    sentence = ai_commentary.draft_sentence("coverage_ratio", ROW)
    nudged = sentence.replace("7.50x", "7.51x")
    check = ai_commentary.verify_sentence(nudged, MART_DF)
    assert not check.blocked


def test_publishable_sentences_excludes_blocked():
    clean = ai_commentary.draft_sentence("win_rate", ROW)
    bad = "Bookings were pretty good this quarter."
    checks = ai_commentary.verify_commentary([clean, bad], MART_DF)
    publishable = ai_commentary.publishable_sentences(checks)
    assert clean in publishable
    assert bad not in publishable
