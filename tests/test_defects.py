"""The 30/30 seeded-defect test: every defect quality_gate.RULES claims to
catch is actually seeded once, and the gate actually catches every one of
them, by name, not just "some count went up."
"""
from __future__ import annotations

from wagering_mart import defects, quality_gate


def _flagged_as_strings(defect_id, flagged):
    if defect_id in ("missing_partition", "stale_partition"):
        return {f"{s}|{p}" for s, p in flagged}
    return {str(x) for x in flagged}


def test_thirty_defect_types_are_seeded():
    _, _, ledger, _ = defects.seed_defects()
    assert ledger["defect_id"].nunique() == 30
    assert set(ledger["defect_id"]) == set(quality_gate.RULES.keys())


def test_gate_catches_thirty_of_thirty_seeded_defects():
    legs, settlements, ledger, ctx = defects.seed_defects()
    results = quality_gate.run_gate(legs, settlements, ctx)

    caught, missed = [], []
    for _, row in ledger.iterrows():
        defect_id, key = row["defect_id"], row["key"]
        flagged_str = _flagged_as_strings(defect_id, results[defect_id])
        if str(key) in flagged_str:
            caught.append(defect_id)
        else:
            missed.append((defect_id, key, results[defect_id][:5]))

    assert missed == [], f"gate missed {len(missed)}/30 seeded defects: {missed}"
    assert len(caught) == 30
    assert not quality_gate.gate_passed(results), "gate must refuse a batch with 30 known defects in it"


def test_gate_passes_clean_batch():
    legs, settlements, stats = defects._base_frames(seed=11)
    ctx = {
        "as_of": settlements["placed_ts"].max(),
        "report_window": (settlements["placed_ts"].min(), settlements["placed_ts"].max() + __import__("pandas").Timedelta(days=1)),
        "expected_partitions": set(map(tuple, settlements[["state", "product"]].drop_duplicates().values)),
        "max_staleness_hours": 24 * 400,  # generous, this is a historical fixture, not "now"
    }
    results = quality_gate.run_gate(legs, settlements, ctx)
    nonempty = {k: v for k, v in results.items() if len(v) > 0}
    assert nonempty == {}, f"clean batch should trip zero rules, tripped: {nonempty}"
    assert quality_gate.gate_passed(results)
