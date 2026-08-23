from datetime import date
from types import SimpleNamespace

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.jobs import scheduler
from app.models.market import Company, MarketIngestionRun, MarketPrice, MarketSnapshot, SectorDailyStats
from app.services.market_ingestion import generate_mock_market_data, run_market_data_cycle


def test_generate_mock_market_data_creates_companies_prices_and_stats():
    with SessionLocal() as db:
        result = generate_mock_market_data(db, days=5, end_date=date(2026, 6, 30))

        company_count = db.scalar(select(func.count()).select_from(Company))
        price_count = db.scalar(select(func.count()).select_from(MarketPrice))
        snapshot_count = db.scalar(select(func.count()).select_from(MarketSnapshot))
        sector_count = db.scalar(select(func.count()).select_from(SectorDailyStats))
        latest_date = db.scalar(select(func.max(MarketPrice.trade_date)))

    assert result["companies"] == 37
    assert result["prices"] == 185
    assert company_count == 37
    assert price_count == 185
    assert snapshot_count == 5
    assert sector_count > 5
    assert latest_date == date(2026, 6, 30)


def test_scheduler_cycle_records_successful_ingestion_run():
    with SessionLocal() as db:
        run = run_market_data_cycle(db, mode="mock")
        snapshot_count = db.scalar(select(func.count()).select_from(MarketSnapshot))

    assert run.status == "success"
    assert run.mode == "mock"
    assert run.attempted_provider == "mock"
    assert run.used_provider == "mock"
    assert run.latest_trade_date is not None
    assert snapshot_count > 0


def test_run_market_data_cycle_records_actual_provider_used(monkeypatch):
    class FakeProvider:
        mode = "auto"
        source = "auto"

        def refresh_latest(self, db):
            return {
                "attempted_provider": "auto",
                "used_provider": "yahoo",
                "prices": 7,
                "latest_trade_date": date(2026, 6, 30),
                "message": "psxdata refresh failed; yahoo fallback succeeded.",
            }

    monkeypatch.setattr("app.services.market_providers.get_market_data_provider", lambda mode: FakeProvider())

    with SessionLocal() as db:
        run = run_market_data_cycle(db, mode="auto")
        stored = db.scalar(select(MarketIngestionRun).where(MarketIngestionRun.id == run.id))

    assert stored is not None
    assert stored.attempted_provider == "auto"
    assert stored.used_provider == "yahoo"
    assert stored.records_written == 7
    assert stored.attempted_count == 7
    assert stored.accepted_count == 7
    assert stored.rejected_count == 0


def test_run_market_data_cycle_marks_explicit_dps_coverage_gap_partial(monkeypatch):
    class FakeProvider:
        mode = "dps"
        source = "dps"

        def refresh_latest(self, db):
            return {
                "attempted_provider": "dps",
                "used_provider": "dps",
                "attempted": 3,
                "accepted": 2,
                "rejected": 1,
                "coverage_status": "partial",
                "prices": 2,
                "latest_trade_date": date(2026, 6, 30),
                "message": "DPS refresh was partial.",
            }

    monkeypatch.setattr("app.services.market_providers.get_market_data_provider", lambda mode: FakeProvider())

    with SessionLocal() as db:
        run = run_market_data_cycle(db, mode="dps")

    assert run.status == "partial"
    assert (run.attempted_count, run.accepted_count, run.rejected_count) == (3, 2, 1)


def test_scheduler_run_once_prints_attempted_and_used_provider(monkeypatch, capsys):
    monkeypatch.setattr(
        scheduler,
        "run_market_data_cycle",
        lambda db, mode: SimpleNamespace(
            status="success",
            mode=mode,
            attempted_provider="auto",
            used_provider="yahoo",
            latest_trade_date=date(2026, 6, 30),
        ),
    )

    scheduler.run_once()
    output = capsys.readouterr().out

    assert "attempted_provider=auto" in output
    assert "used_provider=yahoo" in output


def test_scheduler_succeeds_when_yahoo_fetches_at_least_one_symbol(monkeypatch):
    class FakeYahooProvider:
        mode = "yahoo"
        source = "yahoo"

        def refresh_latest(self, db):
            return {
                "attempted_provider": "yahoo",
                "used_provider": "yahoo",
                "attempted_symbols": ["ENGRO", "ADOS"],
                "successful_symbols": ["ENGRO"],
                "skipped_symbols": ["ADOS"],
                "failed_symbols": [],
                "prices": 1,
                "latest_trade_date": date(2026, 6, 30),
                "message": "Refreshed market data via yahoo. attempted=2 successful=1 skipped=1 failed=0.",
            }

    monkeypatch.setattr("app.services.market_providers.get_market_data_provider", lambda mode: FakeYahooProvider())

    with SessionLocal() as db:
        run = run_market_data_cycle(db, mode="yahoo")

    assert run.status == "success"
    assert run.used_provider == "yahoo"
    assert run.records_written == 1
    assert (run.attempted_count, run.accepted_count, run.rejected_count) == (2, 1, 1)
