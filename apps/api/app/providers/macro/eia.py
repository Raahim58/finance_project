"""Verified EIA daily spot-price workbook parser, not futures or intraday quotes."""

from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

from app.providers.macro.contracts import ProviderObservation

EIA_SERIES = {
    "RWTC": "Cushing, OK WTI Spot Price FOB (Dollars per Barrel)",
    "RBRTE": "Europe Brent Spot Price FOB (Dollars per Barrel)",
}


def parse_daily_spot(frame, source_series_id: str, start: date, end: date):
    expected = EIA_SERIES[source_series_id]
    if frame.shape[0] < 3 or frame.shape[1] != 2:
        raise ValueError("EIA daily spot workbook shape changed")
    if str(frame.iloc[1, 1]).strip() != source_series_id or str(frame.iloc[2, 1]).strip() != expected:
        raise ValueError("EIA daily spot source key, unit or title changed")
    if str(frame.iloc[2, 0]).strip() != "Date":
        raise ValueError("EIA daily spot date header changed")
    rows = {}
    for raw_date, raw_value in frame.iloc[3:].itertuples(index=False, name=None):
        if pd.isna(raw_date) and pd.isna(raw_value):
            continue
        observed = pd.to_datetime(raw_date, errors="raise").date()
        if not start <= observed <= end or pd.isna(raw_value):
            continue
        try:
            value = Decimal(str(raw_value))
        except InvalidOperation as exc:
            raise ValueError("EIA daily spot price is not numeric") from exc
        if not value.is_finite():
            raise ValueError("EIA daily spot price is not finite")
        # Negative WTI observations (April 2020) are real, not parser errors.
        if observed in rows and rows[observed] != value:
            raise ValueError("EIA daily spot workbook has conflicting duplicate dates")
        rows[observed] = value
    return tuple(ProviderObservation(day, value) for day, value in sorted(rows.items()))
