from datetime import date

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.market import Company, MarketPrice, MarketSnapshot, SectorDailyStats
from app.services.market_ingestion import generate_mock_market_data, run_market_data_cycle


def test_generate_mock_market_data_creates_companies_prices_and_stats():
    with SessionLocal() as db:
        result = generate_mock_market_data(db, days=5, end_date=date(2026, 6, 30))

        company_count = db.scalar(select(func.count()).select_from(Company))
        price_count = db.scalar(select(func.count()).select_from(MarketPrice))
        snapshot_count = db.scalar(select(func.count()).select_from(MarketSnapshot))
        sector_count = db.scalar(select(func.count()).select_from(SectorDailyStats))
        latest_date = db.scalar(select(func.max(MarketPrice.trade_date)))

    assert result["companies"] == 16
    assert result["prices"] == 80
    assert company_count == 16
    assert price_count == 80
    assert snapshot_count == 5
    assert sector_count > 5
    assert latest_date == date(2026, 6, 30)


def test_scheduler_cycle_records_successful_ingestion_run():
    with SessionLocal() as db:
        run = run_market_data_cycle(db, mode="mock")
        snapshot_count = db.scalar(select(func.count()).select_from(MarketSnapshot))

    assert run.status == "success"
    assert run.mode == "mock"
    assert run.source == "mock"
    assert run.latest_trade_date is not None
    assert snapshot_count > 0
