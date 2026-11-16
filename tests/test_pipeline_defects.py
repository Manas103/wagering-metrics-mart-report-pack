"""The 30/30 seeded-defect test for the sales-pipeline extension: every
defect quality_gate.RULES claims to catch is actually seeded once, and the
gate actually catches every one of them, by name.
"""
from __future__ import annotations

import pandas as pd

from sales_pipeline_mart import defects, quality_gate


def _flagged_as_strings(flagged):
    return {("|".join(map(str, f)) if isinstance(f, tuple) else str(f)) for f in flagged}


def test_thirty_defect_types_are_seeded():
    _, _, ledger, _ = defects.seed_defects()
    assert ledger["defect_id"].nunique() == 30
    assert set(ledger["defect_id"]) == set(quality_gate.RULES.keys())


def test_gate_catches_thirty_of_thirty_seeded_defects():
    pipeline, bookings, ledger, ctx = defects.seed_defects()
    results = quality_gate.run_gate(pipeline, bookings, ctx)

    caught, missed = [], []
    for _, row in ledger.iterrows():
        defect_id, key = row["defect_id"], row["key"]
        if str(key) in _flagged_as_strings(results[defect_id]):
            caught.append(defect_id)
        else:
            missed.append((defect_id, key, results[defect_id][:5]))

    assert missed == [], f"gate missed {len(missed)}/30 seeded defects: {missed}"
    assert len(caught) == 30
    assert not quality_gate.gate_passed(results), "gate must refuse a batch with 30 known defects in it"


def test_gate_passes_clean_batch():
    pipeline, bookings, stats = defects._base_frames(seed=11)
    ctx = {
        "as_of": pipeline["event_date"].max(),
        "report_window": (pipeline["event_date"].min(), pipeline["event_date"].max() + pd.Timedelta(days=1)),
        "expected_partitions": set(map(tuple, pipeline[["region", "product", "segment"]].drop_duplicates().values)),
        "max_staleness_days": 1000,  # generous (longer than the whole report
                                      # window, ~669 days): this is a historical
                                      # fixture, not "now"
    }
    results = quality_gate.run_gate(pipeline, bookings, ctx)
    nonempty = {k: v for k, v in results.items() if len(v) > 0}
    assert nonempty == {}, f"clean batch should trip zero rules, tripped: {nonempty}"
    assert quality_gate.gate_passed(results)
