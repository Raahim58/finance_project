from datetime import date
from decimal import Decimal
import json

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import DataQualityIssue, Instrument, MarketObservation
from app.core.config import settings
from app.services.canonical_market_service import latest_price, price_series
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import LatestPriceRow


def _row(source_url: str, close: str = "101", high: str = "102") -> LatestPriceRow:
    return LatestPriceRow(
        symbol="TEST", trade_date=date(2026, 8, 7), close=Decimal(close),
        previous_close=Decimal("100"), open=Decimal("100"), high=Decimal(high),
        low=Decimal("99"), volume=1000, name="Test Limited", sector="Test",
        source_url=source_url,
    )


def test_canonical_reconciliation_uses_source_priority_and_records_conflict():
    with SessionLocal() as db:
        persist_market_data(db, latest_prices=[_row("https://finance.yahoo.com")], source="yahoo")
        persist_market_data(db, latest_prices=[_row("https://dps.psx.com.pk", close="100.5")], source="dps")
        canonical = price_series(db, "TEST", allow_legacy_fallback=False)
        selected = db.scalar(select(func.count()).select_from(MarketObservation).where(MarketObservation.is_selected.is_(True)))
        conflicts = db.scalar(select(func.count()).select_from(DataQualityIssue).where(DataQualityIssue.rule == "source_conflict_not_selected"))
    assert len(canonical) == 1
    assert canonical[0].source == "dps"
    assert canonical[0].close == Decimal("100.5")
    assert selected == 1
    assert conflicts == 1


def test_invalid_observed_ohlc_is_rejected_not_synthesized():
    with SessionLocal() as db:
        result = persist_market_data(db, latest_prices=[_row("https://dps.psx.com.pk", high="90")], source="dps")
        legacy = db.scalar(select(func.count()).select_from(MarketPrice).where(MarketPrice.symbol == "TEST"))
        issue = db.scalar(select(DataQualityIssue).where(DataQualityIssue.rule == "invalid_ohlc_high"))
    assert result["prices"] == 0
    assert result["rejected"] == 1
    assert legacy == 0
    assert issue is not None


def test_live_mode_never_returns_mock_as_canonical(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    with SessionLocal() as db:
        persist_market_data(db, latest_prices=[_row("normalized://mock/fixture")], source="mock")
        assert price_series(db, "TEST") == []


def test_live_mode_prefers_observed_and_excludes_mock_only_dates(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "auto")
    observed = _row("https://dps.psx.com.pk/historical", close="105", high="106")
    mock_only = LatestPriceRow(
        symbol="TEST", trade_date=date(2026, 8, 6), close=Decimal("99"),
        previous_close=Decimal("98"), open=Decimal("98"), high=Decimal("100"),
        low=Decimal("97"), volume=10, name="Test Limited", sector="Test",
        source_url="normalized://mock/fixture",
    )
    with SessionLocal() as db:
        persist_market_data(db, latest_prices=[mock_only], source="mock")
        persist_market_data(db, latest_prices=[observed], source="dps")
        rows = price_series(db, "TEST")
        metadata = json.loads(db.scalar(select(Instrument).where(Instrument.symbol == "TEST")).metadata_json)
    assert [(row.trade_date, row.source) for row in rows] == [(date(2026, 8, 7), "dps")]
    assert metadata["data_classification"] == "observed"
    assert metadata["identity_source"] == "dps"


def test_latest_price_queries_only_the_latest_canonical_observation():
    older = LatestPriceRow(
        symbol="TEST", trade_date=date(2026, 8, 6), close=Decimal("99"),
        previous_close=Decimal("98"), open=Decimal("98"), high=Decimal("100"),
        low=Decimal("97"), volume=10, name="Test Limited", sector="Test",
        source_url="https://dps.psx.com.pk/historical",
    )
    with SessionLocal() as db:
        persist_market_data(db, latest_prices=[older, _row("https://dps.psx.com.pk")], source="dps")
        latest = latest_price(db, "test")
        historical = latest_price(db, "TEST", as_of=date(2026, 8, 6))

    assert latest is not None and latest.trade_date == date(2026, 8, 7)
    assert historical is not None and historical.trade_date == date(2026, 8, 6)
