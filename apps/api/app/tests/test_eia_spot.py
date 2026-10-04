from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.providers.macro.eia import EIA_SERIES, parse_daily_spot
from app.ingestion.macro_catalog import MACRO_SERIES_BY_KEY


def frame():
    return pd.DataFrame([
        ['Back to Contents', 'Data 1: ' + EIA_SERIES['RWTC']],
        ['Sourcekey', 'RWTC'], ['Date', EIA_SERIES['RWTC']],
        [pd.Timestamp('2020-04-20'), -36.98],
        [pd.Timestamp('2020-04-21'), 8.91],
        [pd.Timestamp('2020-04-22'), None],
    ])


def test_observed_eia_shape_preserves_negative_price_and_filters_dates():
    rows = parse_daily_spot(frame(), 'RWTC', date(2020, 4, 20), date(2020, 4, 21))
    assert [r.value for r in rows] == [Decimal('-36.98'), Decimal('8.91')]
    assert len(parse_daily_spot(frame(), 'RWTC', date(2020, 4, 21), date(2020, 4, 21))) == 1


def test_eia_rejects_wrong_series_units_and_conflicting_dates():
    with pytest.raises(ValueError, match='source key'):
        parse_daily_spot(frame(), 'RBRTE', date(2020, 1, 1), date(2020, 12, 31))
    f = pd.concat([frame(), pd.DataFrame([[pd.Timestamp('2020-04-20'), 25]])], ignore_index=True)
    with pytest.raises(ValueError, match='conflicting'):
        parse_daily_spot(f, 'RWTC', date(2020, 1, 1), date(2020, 12, 31))


def test_macro_catalog_keeps_gold_monthly_and_oil_daily():
    assert MACRO_SERIES_BY_KEY['GLOBAL_GOLD_USD_TROY_OZ'].frequency == 'monthly'
    assert MACRO_SERIES_BY_KEY['WTI_USD_BBL'].frequency == 'daily'
    assert MACRO_SERIES_BY_KEY['BRENT_USD_BBL'].providers[0].source_series_id == 'RBRTE'
