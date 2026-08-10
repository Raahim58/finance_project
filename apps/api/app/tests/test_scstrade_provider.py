import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.providers.market.scstrade import ScsTradeProvider


FIXTURES = Path(__file__).parent / "fixtures" / "providers" / "scstrade"


def test_scstrade_observed_chart_contract():
    payload = json.loads((FIXTURES / "mebl_history.sample.json").read_text())
    rows = ScsTradeProvider.parse_history(payload)
    assert [row.trade_date for row in rows] == [date(2026, 8, 6), date(2026, 8, 7)]
    assert rows[-1].close == Decimal("586.84")
    assert rows[-1].volume == 1_367_419


def test_scstrade_quarantines_impossible_ohlc():
    payload = {"d": [{"trading_Date": "/Date(1786042800000)/", "trading_open": 100, "trading_high": 90, "trading_low": 80, "trading_close": 95, "trading_vol": 1, "trading_change": 0}]}
    assert ScsTradeProvider.parse_history(payload) == []
