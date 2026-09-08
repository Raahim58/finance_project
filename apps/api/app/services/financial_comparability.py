"""Calculation-only observed metrics; never mix source, basis, units or periods."""
from collections import defaultdict
from decimal import Decimal


def comparable_series(rows, metric):
    groups = defaultdict(list)
    for row in rows:
        if row.metric != metric or row.period_end is None or row.quality_status != "observed":
            continue
        groups[(row.source, row.unit, row.currency, row.classification)].append(row)
    candidates = []
    for group in groups.values():
        ordered = sorted(group, key=lambda row: (row.period_end, row.retrieved_at), reverse=True)
        unique = {}
        for row in ordered:
            unique.setdefault(row.period_end, row)
        candidates.append(list(unique.values()))
    # A disagreement at the most recent period is not an arbitrary source preference.
    if not candidates:
        return []
    candidates.sort(key=lambda series: (series[0].period_end, series[0].source), reverse=True)
    latest = candidates[0][0]
    contemporaries = [series[0] for series in candidates if series[0].period_end == latest.period_end]
    if len({(row.value, row.unit, row.currency) for row in contemporaries}) > 1:
        return []
    return candidates[0]


def growth(series):
    if len(series) < 2 or series[1].value == 0:
        return None
    # Annual periods must be adjacent; a missing year is not annual growth.
    gap = (series[0].period_end - series[1].period_end).days
    if not 330 <= gap <= 400:
        return None
    return (series[0].value - series[1].value) / abs(series[1].value)


def margin(numerator, denominator):
    if not numerator or not denominator:
        return None
    top, bottom = numerator[0], denominator[0]
    if (top.period_end, top.source, top.unit, top.currency, top.classification) != (
        bottom.period_end, bottom.source, bottom.unit, bottom.currency, bottom.classification):
        return None
    return top.value / bottom.value if bottom.value else None
