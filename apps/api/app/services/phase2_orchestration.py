from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.jobs.phase2_tasks import broad_fundamentals, dps_history, financial_download_catalog, financial_extract
from app.models.document import Document
from app.models.market import Company
from app.models.workstation import IngestionCoverage, Instrument
from app.providers.fundamentals.extraction import FINANCIAL_EXTRACTION_VERSION
from app.services.coverage_service import coverage, is_queueable, reserve_and_publish
from app.services.screening_service import deep_instrument_ids


def _months(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        yield cursor.year, cursor.month
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)


def incremental_catalog_dispatch_key(now: datetime) -> str:
    bucket_hour = now.hour - (now.hour % settings.phase2_catalog_refresh_hours)
    bucket = now.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
    return f"incremental:{bucket.isoformat()}"


def enqueue_reconstructable_phase2_work(
    db: Session,
    now: datetime | None = None,
    queue_limits: dict[str, int] | None = None,
) -> dict[str, int]:
    """Publish bounded, independently sized queues from durable Postgres coverage."""
    now = now or datetime.now(UTC)
    limits = queue_limits or {
        "broad_fundamentals": settings.phase2_broad_queue_target,
        "dps_history": settings.phase2_history_queue_target,
        "financial_download": settings.phase2_download_queue_target,
        "financial_extract": settings.phase2_extract_queue_target,
    }
    queued = {name: 0 for name in limits}
    active = list(db.scalars(
        select(Instrument)
        .join(Company, Company.id == Instrument.company_id)
        .where(Company.is_active.is_(True))
        .order_by(Instrument.symbol)
    ))

    for instrument in active:
        if queued.get("broad_fundamentals", 0) >= limits.get("broad_fundamentals", 0):
            break
        state = coverage(db, instrument.id, "standardized_fundamentals", "current", "dps")
        if is_queueable(state, now, refresh_after=timedelta(days=30)) and reserve_and_publish(
            db, state, broad_fundamentals, (instrument.symbol,), now
        ):
            queued["broad_fundamentals"] += 1

    deep_ids = deep_instrument_ids(db)
    end = now.date()
    start = end - timedelta(days=5 * 366)
    for instrument in (row for row in active if row.id in deep_ids):
        if queued.get("dps_history", 0) < limits.get("dps_history", 0):
            for year, month in _months(start, end):
                if queued["dps_history"] >= limits["dps_history"]:
                    break
                period_key = f"{year:04d}-{month:02d}"
                state = coverage(db, instrument.id, "price_history", period_key, "dps")
                if is_queueable(state, now) and reserve_and_publish(
                    db, state, dps_history, (instrument.symbol, year, month), now
                ):
                    queued["dps_history"] += 1

        if queued.get("financial_download", 0) < limits.get("financial_download", 0):
            historical_key = f"historical:{end.year}"
            historical = coverage(db, instrument.id, "report_catalog_dispatch", historical_key, "psx_financials")
            if historical.status != "complete":
                if is_queueable(historical, now) and reserve_and_publish(
                    db, historical, financial_download_catalog, (instrument.symbol, "historical", end.year, historical_key), now
                ):
                    queued["financial_download"] += 1
            else:
                incremental_key = incremental_catalog_dispatch_key(now)
                incremental = coverage(db, instrument.id, "report_catalog_dispatch", incremental_key, "psx_financials")
                if is_queueable(incremental, now) and reserve_and_publish(
                    db, incremental, financial_download_catalog, (instrument.symbol, "incremental", end.year, incremental_key), now
                ):
                    queued["financial_download"] += 1

        if all(queued.get(name, 0) >= limit for name, limit in limits.items()):
            break

    if queued.get("financial_extract", 0) < limits.get("financial_extract", 0):
        instruments_by_symbol = {row.symbol: row for row in active}
        documents = db.scalars(
            select(Document)
            .where(Document.artifact_id.is_not(None))
            .order_by(Document.downloaded_at, Document.id)
        )
        for document in documents:
            if queued["financial_extract"] >= limits["financial_extract"]:
                break
            instrument = instruments_by_symbol.get(document.symbol or "")
            if instrument is None or instrument.id not in deep_ids:
                continue
            state = coverage(db, instrument.id, "financial_extract", document.id, "psx_financials")
            if document.status == "needs_ocr" and document.extraction_version != FINANCIAL_EXTRACTION_VERSION:
                state.status = "missing"
                state.retry_count = 0
                state.error_class = None
                state.error_message = None
            if is_queueable(state, now) and reserve_and_publish(
                db, state, financial_extract, (document.id,), now
            ):
                queued["financial_extract"] += 1

    return queued
