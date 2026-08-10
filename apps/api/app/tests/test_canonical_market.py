from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import DataQualityIssue, MarketObservation
from app.services.canonical_market_service import price_series
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
