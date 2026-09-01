"""Small SQL-generation helpers used only by generate.py.

Kept separate so generate.py reads as the data model, not string plumbing.
"""
from __future__ import annotations


def weighted_case(rand_col: str, weights: dict) -> str:
    """Build a SQL CASE expression that turns a uniform-[0,1) draw already
    materialized in `rand_col` into a weighted categorical pick.

    `rand_col` must already be a materialized column (the output of a prior
    SELECT), never a bare call to random(), otherwise each WHEN branch would
    re-evaluate random() independently and the weighting would be wrong.
    """
    total = sum(weights.values())
    items = list(weights.items())
    lines = []
    cum = 0.0
    for i, (key, w) in enumerate(items):
        cum += w
        threshold = cum / total
        if i == len(items) - 1:
            lines.append(f"ELSE '{key}'")
        else:
            lines.append(f"WHEN {rand_col} < {threshold!r} THEN '{key}'")
    return "CASE " + " ".join(lines) + " END"
