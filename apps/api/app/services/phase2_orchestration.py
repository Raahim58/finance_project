from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.phase2_tasks import broad_fundamentals, dps_history, financial_download_catalog
from app.models.market import Company
from app.models.workstation import IngestionCoverage, Instrument
from app.services.coverage_service import coverage
from app.services.screening_service import deep_instrument_ids


def _months(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        yield cursor.year, cursor.month
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)


def enqueue_reconstructable_phase2_work(db: Session, now: datetime | None = None, limit: int = 500) -> dict[str, int]:
    """Rebuild broker work solely from Postgres state; safe after Redis loss."""
    now = now or datetime.now(UTC)
    queued = {"broad_fundamentals": 0, "dps_history": 0, "financial_download": 0}
    active = list(db.scalars(select(Instrument).join(Company, Company.id == Instrument.company_id).where(Company.is_active.is_(True)).order_by(Instrument.symbol)))
    stale_before = now - timedelta(days=30)
    abandoned_before = now - timedelta(hours=1)
    for instrument in active:
        state = coverage(db, instrument.id, "standardized_fundamentals", "current", "dps")
        if state.status in {"missing", "failed", "partial"} or (state.status == "running" and (state.attempted_at is None or state.attempted_at < abandoned_before)) or (state.completed_at and state.completed_at < stale_before):
            broad_fundamentals.delay(instrument.symbol); queued["broad_fundamentals"] += 1
            if sum(queued.values()) >= limit: break
    deep_ids = deep_instrument_ids(db)
    end = now.date(); start = end - timedelta(days=5 * 366)
    for instrument in (row for row in active if row.id in deep_ids):
        for year, month in _months(start, end):
            period_key = f"{year:04d}-{month:02d}"
            state = coverage(db, instrument.id, "price_history", period_key, "dps")
            if state.status in {"missing", "failed", "partial"} or (state.status == "running" and (state.attempted_at is None or state.attempted_at < abandoned_before)):
                dps_history.delay(instrument.symbol, year, month); queued["dps_history"] += 1
                if sum(queued.values()) >= limit: break
        financial_download_catalog.delay(instrument.symbol, "historical")
        queued["financial_download"] += 1
        if sum(queued.values()) >= limit: break
    db.commit()
    return queued
