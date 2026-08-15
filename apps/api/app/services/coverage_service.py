from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workstation import IngestionCoverage
from app.core.config import settings


def coverage(db: Session, instrument_id: str, dataset_type: str, period_key: str, source: str) -> IngestionCoverage:
    row = db.scalar(select(IngestionCoverage).where(
        IngestionCoverage.instrument_id == instrument_id,
        IngestionCoverage.dataset_type == dataset_type,
        IngestionCoverage.period_key == period_key,
        IngestionCoverage.source == source,
    ))
    if row is None:
        row = IngestionCoverage(instrument_id=instrument_id, dataset_type=dataset_type, period_key=period_key, source=source, status="missing")
        db.add(row); db.flush()
    return row


def begin(row: IngestionCoverage) -> None:
    row.status = "running"; row.attempted_at = datetime.now(UTC)
    row.error_class = None; row.error_message = None


def complete(row: IngestionCoverage, count: int, diagnostics: list[str] | None = None) -> None:
    row.status = "complete" if count else "partial"
    row.completed_at = datetime.now(UTC); row.item_count = count
    row.diagnostics_json = json.dumps({"messages": diagnostics or []}, sort_keys=True)


def fail(row: IngestionCoverage, exc: Exception) -> None:
    row.status = "failed"; row.retry_count += 1
    row.error_class = type(exc).__name__; row.error_message = str(exc)[:2000]
    row.completed_at = None


def is_queueable(row: IngestionCoverage, now: datetime, *, refresh_after: timedelta | None = None) -> bool:
    attempted = row.attempted_at
    if row.status == "missing":
        return True
    if row.status == "failed":
        if row.retry_count >= settings.phase2_max_retries:
            return False
        delay = timedelta(seconds=min(3600, settings.phase2_retry_backoff_seconds * (2 ** max(0, row.retry_count - 1))))
        return attempted is None or attempted <= now - delay
    if row.status == "queued":
        return attempted is None or attempted <= now - timedelta(minutes=15)
    if row.status == "running":
        return attempted is None or attempted <= now - timedelta(hours=1)
    if row.status == "complete" and refresh_after is not None:
        return row.completed_at is not None and row.completed_at <= now - refresh_after
    return False


def reserve_and_publish(db: Session, row: IngestionCoverage, task, args: tuple, now: datetime) -> bool:
    snapshot = (row.status, row.attempted_at, row.completed_at, row.retry_count)
    locked = db.scalar(
        select(IngestionCoverage)
        .where(IngestionCoverage.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or (locked.status, locked.attempted_at, locked.completed_at, locked.retry_count) != snapshot:
        db.rollback()
        return False
    locked.status = "queued"
    locked.attempted_at = now
    locked.error_class = None
    locked.error_message = None
    db.commit()
    try:
        task.delay(*args)
    except Exception as exc:
        db.refresh(locked)
        fail(locked, exc)
        db.commit()
        return False
    return True
