from decimal import Decimal
import json
from pathlib import Path

from datetime import date

import pandas as pd
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.services.market_providers import (
    AutoMarketDataProvider,
    DpsMarketDataProvider,
    LatestPriceRow,
    MockMarketDataProvider,
    PsxDataMarketDataProvider,
    YahooFinanceMarketDataProvider,
    get_market_data_provider,
)


def test_market_provider_factory_returns_expected_provider_types():
    assert isinstance(get_market_data_provider("mock"), MockMarketDataProvider)
    assert isinstance(get_market_data_provider("psxdata"), PsxDataMarketDataProvider)
    assert isinstance(get_market_data_provider("yahoo"), YahooFinanceMarketDataProvider)
    assert isinstance(get_market_data_provider("auto"), AutoMarketDataProvider)
    assert isinstance(get_market_data_provider("dps"), DpsMarketDataProvider)


def test_psxdata_provider_handles_import_failure_gracefully(monkeypatch):
    provider = PsxDataMarketDataProvider()
    monkeypatch.setattr(provider, "_load_client", lambda: (_ for _ in ()).throw(RuntimeError("import failed")))

    health = provider.health_check()

    assert health["ok"] is False
    assert "import failed" in health["detail"]


def test_yahoo_symbol_mapping():
    assert YahooFinanceMarketDataProvider.resolve_yahoo_symbol("ENGRO") == "ENGRO.KA"


def test_auto_provider_falls_back_to_yahoo_if_dps_fails(monkeypatch):
    monkeypatch.setattr(
        DpsMarketDataProvider,
        "fetch_latest_prices",
        lambda self, symbols=None: (_ for _ in ()).throw(RuntimeError("psxdata down")),
    )
    monkeypatch.setattr(
        YahooFinanceMarketDataProvider,
        "fetch_latest_prices",
        lambda self, symbols=None: [
            LatestPriceRow(
                symbol="ENGRO",
                name="Engro Corporation Limited",
                sector="Fertilizer",
                trade_date=date(2026, 6, 30),
                open=100,
                high=110,
                low=99,
                close=108,
                previous_close=105,
                volume=1000,
                source_url="https://finance.yahoo.com/quote/ENGRO.KA",
            )
        ],
    )

    provider = AutoMarketDataProvider()

    with SessionLocal() as db:
        result = provider.refresh_latest(db)
        price_count = db.scalar(select(func.count()).select_from(MarketPrice))
        latest_price = db.scalar(select(MarketPrice).where(MarketPrice.symbol == "ENGRO"))

    assert result["attempted_provider"] == "auto"
    assert result["used_provider"] == "yahoo"
    assert price_count == 1
    assert latest_price is not None
    assert latest_price.source == "yahoo"


DPS_FIXTURES = Path(__file__).parent / "fixtures" / "providers" / "dps"


def test_dps_symbol_contract_fixture():
    payload = json.loads((DPS_FIXTURES / "symbols.sample.json").read_text())
    rows = DpsMarketDataProvider.parse_symbols(payload)
    assert [row["symbol"] for row in rows] == ["MEBL", "OGDC", "SYS"]
    assert rows[0]["sector"] == "COMMERCIAL BANKS"
    assert rows[0]["is_debt"] is False


def test_dps_datewise_history_contract_and_debt_filter():
    html = (DPS_FIXTURES / "historical_date.sample.html").read_text()
    rows = DpsMarketDataProvider.parse_datewise_history(html, date(2026, 8, 7))
    assert [row.symbol for row in rows] == ["786", "MEBL"]
    assert rows[1].previous_close == Decimal("587.92")
    assert rows[1].high == Decimal("592.97")
    assert rows[1].volume == 1_367_419


def test_dps_symbol_history_is_normalized_oldest_first():
    html = (DPS_FIXTURES / "historical_mebl.sample.html").read_text()
    rows = DpsMarketDataProvider.parse_symbol_history(html, "MEBL")
    assert [row.trade_date for row in rows] == [date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10)]
    assert rows[1].previous_close == Decimal("587.93")
    assert rows[2].volume == 48_388


def test_dps_parser_rejects_contract_header_drift():
    html = (DPS_FIXTURES / "historical_date.sample.html").read_text().replace("LDCP", "PREVIOUS")
    import pytest
    with pytest.raises(ValueError, match="headers changed"):
        DpsMarketDataProvider.parse_datewise_history(html, date(2026, 8, 7))


def test_dps_daily_manifest_uses_observed_links():
    html = (DPS_FIXTURES / "daily_manifest.sample.html").read_text()
    links = DpsMarketDataProvider.parse_daily_manifest(html)
    assert links[2] == {"label": "ZIP", "href": "/download/symbol_price/2026-08-07.zip", "format": "zip"}


def test_provider_normalization_converts_nan_to_none(monkeypatch):
    provider = PsxDataMarketDataProvider()
    monkeypatch.setattr(
        provider,
        "_latest_payload",
        lambda symbols=None: [
            {
                "symbol": "ENGRO",
                "date": "2026-06-30",
                "open": float("nan"),
                "high": "NaN",
                "low": Decimal("NaN"),
                "close": float("inf"),
                "previous_close": "-inf",
                "volume": "",
                "market_cap": "nan",
            }
        ],
    )

    rows = provider.fetch_latest_prices()

    assert len(rows) == 1
    row = rows[0]
    assert row.open is None
    assert row.high is None
    assert row.low is None
    assert row.close is None
    assert row.previous_close is None
    assert row.volume is None
    assert row.market_cap is None


def test_yahoo_provider_requires_observed_or_explicit_symbols(monkeypatch):
    provider = YahooFinanceMarketDataProvider()

    seen_symbols: list[str] = []

    class FakeTicker:
        def __init__(self, yahoo_symbol: str):
            seen_symbols.append(yahoo_symbol)

        def history(self, period: str, auto_adjust: bool):
            return pd.DataFrame(
                [{"Open": 100, "High": 110, "Low": 99, "Close": 108, "Volume": 1000}],
                index=pd.to_datetime(["2026-06-30"]),
            )

    fake_yf = type("FakeYF", (), {"Ticker": FakeTicker})
    monkeypatch.setattr(provider, "_load_yfinance", lambda: fake_yf)

    rows = provider.fetch_latest_prices(["ENGRO", "SYS"])

    assert [row.symbol for row in rows] == ["ENGRO", "SYS"]
    assert seen_symbols == ["ENGRO.KA", "SYS.KA"]


def test_yahoo_provider_skips_invalid_symbols_without_inserting_zero_rows(monkeypatch):
    provider = YahooFinanceMarketDataProvider()

    class FakeTicker:
        def __init__(self, yahoo_symbol: str):
            self.yahoo_symbol = yahoo_symbol

        def history(self, period: str, auto_adjust: bool):
            if self.yahoo_symbol == "ADOS.KA":
                return pd.DataFrame()
            return pd.DataFrame(
                [{"Open": 100, "High": 110, "Low": 99, "Close": 108, "Volume": 1000}],
                index=pd.to_datetime(["2026-06-30"]),
            )

    fake_yf = type("FakeYF", (), {"Ticker": FakeTicker})
    monkeypatch.setattr(provider, "_load_yfinance", lambda: fake_yf)

    with SessionLocal() as db:
        rows = provider.fetch_latest_prices(["ENGRO", "ADOS"])
        from app.services.market_ingestion import persist_market_data
        result = persist_market_data(db, latest_prices=rows, source="yahoo") | provider.last_ingestion_summary
        prices = db.scalars(select(MarketPrice).order_by(MarketPrice.symbol.asc())).all()

    assert result["attempted_symbols"] == ["ENGRO", "ADOS"]
    assert result["successful_symbols"] == ["ENGRO"]
    assert result["skipped_symbols"] == ["ADOS"]
    assert result["failed_symbols"] == []
    assert [price.symbol for price in prices] == ["ENGRO"]
    assert prices[0].volume == 1000
    assert prices[0].close == Decimal("108.0000")


def test_yahoo_provider_uses_only_explicit_symbols(monkeypatch):
    provider = YahooFinanceMarketDataProvider()

    seen_symbols: list[str] = []

    class FakeTicker:
        def __init__(self, yahoo_symbol: str):
            seen_symbols.append(yahoo_symbol)

        def history(self, period: str, auto_adjust: bool):
            return pd.DataFrame(
                [{"Open": 100, "High": 110, "Low": 99, "Close": 108, "Volume": 1000}],
                index=pd.to_datetime(["2026-06-30"]),
            )

    fake_yf = type("FakeYF", (), {"Ticker": FakeTicker})
    monkeypatch.setattr(provider, "_load_yfinance", lambda: fake_yf)

    rows = provider.fetch_latest_prices(symbols=["LUCK"])

    assert [row.symbol for row in rows] == ["LUCK"]
    assert seen_symbols == ["LUCK.KA"]
