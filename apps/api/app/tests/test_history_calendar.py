from datetime import date
from types import SimpleNamespace

from app.db.session import SessionLocal
from app.services.ingestion_service import run_historical_backfill
from app.services.trading_calendar_service import sessions_between, upsert_calendar_day


def test_explicit_psx_closure_overrides_weekday_assumption():
    with SessionLocal() as db:
        upsert_calendar_day(db, session_date=date(2026, 8, 10), is_session=False, reason="Observed closure", artifact_id=None)
        sessions = sessions_between(db, date(2026, 8, 7), date(2026, 8, 11))
    assert [row.session_date for row in sessions] == [date(2026, 8, 7), date(2026, 8, 11)]
    assert all(row.session_date != date(2026, 8, 10) for row in sessions)


def test_failed_history_job_can_retry_same_idempotency_key(monkeypatch):
    class Provider:
        calls = 0

        def fetch_symbol_history(self, symbol, start, end):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary source failure")
            return [SimpleNamespace(
                symbol=symbol, trade_date=start, close=1, previous_close=1,
                open=1, high=1, low=1, volume=1, market_cap=None,
                source_url="https://dps.psx.com.pk", name="Test Limited", sector="Test",
            )]

    provider = Provider()
    monkeypatch.setattr("app.services.ingestion_service.get_market_data_provider", lambda name: provider)
    with SessionLocal() as db:
        first = run_historical_backfill(db, provider_name="dps", symbols=["TEST"], start=date(2026, 8, 7), end=date(2026, 8, 7), run_key="retry-test")
        assert first.status == "failed"
        second = run_historical_backfill(db, provider_name="dps", symbols=["TEST"], start=date(2026, 8, 7), end=date(2026, 8, 7), run_key="retry-test")
        assert second.id == first.id
        assert second.status == "completed"
        assert second.retry_count == 1
