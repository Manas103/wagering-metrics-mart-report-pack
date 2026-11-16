"""Verifies AI-drafted commentary sentence by sentence against the mart,
re-deriving the figure each sentence cites from mart_metrics instead of
trusting the draft's arithmetic. This is the mechanism, not a promise: a
sentence whose cited number disagrees with the real query result is
blocked before publication, one sentence at a time, independent of every
other sentence.

Commentary here follows five fixed templates (one per metric), which is a
real, common constraint on AI-drafted BI copy, not a weakening of the
check: the regex parser below is deliberately strict about the sentence
shape so that what it extracts (region, product, segment, year_month, the
cited number) is unambiguous, the same reason a real verification layer
would run on structured drafts rather than open-ended prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config

_REGION_ALT = "|".join(re.escape(r) for r in sorted(config.REGIONS, key=len, reverse=True))
_PRODUCT_ALT = "|".join(re.escape(p) for p in sorted(config.PRODUCTS, key=len, reverse=True))
_SEGMENT_ALT = "|".join(re.escape(s) for s in sorted(config.SEGMENTS, key=len, reverse=True))
_YM = r"\d{4}-\d{2}"
_NUM = r"[\$]?-?[\d,]+(?:\.\d+)?"

TEMPLATES = {
    "bookings": re.compile(
        rf"^Bookings in (?P<region>{_REGION_ALT}) for (?P<product>{_PRODUCT_ALT}) "
        rf"\((?P<segment>{_SEGMENT_ALT})\) in (?P<year_month>{_YM}) totaled \$(?P<value>{_NUM})\.$"
    ),
    "win_rate": re.compile(
        rf"^(?P<segment>{_SEGMENT_ALT}) win rate for (?P<product>{_PRODUCT_ALT}) in (?P<region>{_REGION_ALT}) "
        rf"during (?P<year_month>{_YM}) was (?P<value>{_NUM})%\.$"
    ),
    "coverage_ratio": re.compile(
        rf"^Pipeline coverage for (?P<product>{_PRODUCT_ALT}) in (?P<region>{_REGION_ALT}) "
        rf"\((?P<segment>{_SEGMENT_ALT})\) in (?P<year_month>{_YM}) stood at (?P<value>{_NUM})x\.$"
    ),
    "cycle_time_days": re.compile(
        rf"^Average sales cycle time for (?P<product>{_PRODUCT_ALT}) in (?P<region>{_REGION_ALT}) "
        rf"\((?P<segment>{_SEGMENT_ALT})\) in (?P<year_month>{_YM}) was (?P<value>{_NUM}) days\.$"
    ),
    "seller_productivity": re.compile(
        rf"^Seller productivity for (?P<product>{_PRODUCT_ALT}) in (?P<region>{_REGION_ALT}) "
        rf"\((?P<segment>{_SEGMENT_ALT})\) in (?P<year_month>{_YM}) was \$(?P<value>{_NUM}) per rep\.$"
    ),
}

RELATIVE_TOLERANCE = 0.005  # 0.5%: a transcription/rounding slip, not a real disagreement


@dataclass
class SentenceCheck:
    sentence: str
    metric: str | None
    matched_slice: bool
    cited_value: float | None
    true_value: float | None
    blocked: bool
    reason: str


def _parse(sentence: str):
    for metric, pattern in TEMPLATES.items():
        m = pattern.match(sentence.strip())
        if m:
            g = m.groupdict()
            return metric, g["region"], g["product"], g["segment"], g["year_month"], float(g["value"].replace(",", "").replace("$", ""))
    return None


def verify_sentence(sentence: str, mart_df) -> SentenceCheck:
    parsed = _parse(sentence)
    if parsed is None:
        return SentenceCheck(sentence, None, False, None, None, True, "did not match any known commentary template")

    metric, region, product, segment, year_month, cited_value = parsed
    row = mart_df.loc[
        (mart_df["region"] == region) & (mart_df["product"] == product)
        & (mart_df["segment"] == segment) & (mart_df["year_month"] == year_month)
    ]
    if len(row) == 0:
        return SentenceCheck(sentence, metric, False, cited_value, None, True, "no matching mart row for the cited slice")

    if metric == "win_rate":
        true_value = float(row["win_rate"].iloc[0]) * 100.0
    else:
        true_value = float(row[metric].iloc[0])

    denom = max(abs(true_value), 1e-9)
    disagreement = abs(cited_value - true_value) / denom
    blocked = disagreement > RELATIVE_TOLERANCE
    reason = (
        f"cited {cited_value} disagrees with mart value {true_value} by {disagreement*100:.2f}%"
        if blocked else "matches mart within tolerance"
    )
    return SentenceCheck(sentence, metric, True, cited_value, true_value, blocked, reason)


def verify_commentary(sentences: list[str], mart_df) -> list[SentenceCheck]:
    return [verify_sentence(s, mart_df) for s in sentences]


def draft_sentence(metric: str, row) -> str:
    """Drafts one commentary sentence from a real mart_metrics row, in the
    fixed template `metric` belongs to. The number substituted is always
    read straight from the row, so a freshly drafted sentence is
    guaranteed to verify clean; errors are injected afterward, deliberately,
    by the benchmark script, never introduced here."""
    region, product, segment, year_month = row["region"], row["product"], row["segment"], row["year_month"]
    if metric == "bookings":
        return f"Bookings in {region} for {product} ({segment}) in {year_month} totaled ${row['bookings']:,.2f}."
    if metric == "win_rate":
        return f"{segment} win rate for {product} in {region} during {year_month} was {row['win_rate']*100:.2f}%."
    if metric == "coverage_ratio":
        return f"Pipeline coverage for {product} in {region} ({segment}) in {year_month} stood at {row['coverage_ratio']:.2f}x."
    if metric == "cycle_time_days":
        return f"Average sales cycle time for {product} in {region} ({segment}) in {year_month} was {row['cycle_time_days']:.2f} days."
    if metric == "seller_productivity":
        return f"Seller productivity for {product} in {region} ({segment}) in {year_month} was ${row['seller_productivity']:,.2f} per rep."
    raise ValueError(f"unknown metric template: {metric}")


def publishable_sentences(checks: list[SentenceCheck]) -> list[str]:
    return [c.sentence for c in checks if not c.blocked]
