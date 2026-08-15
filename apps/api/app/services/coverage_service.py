from datetime import UTC, datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workstation import IngestionCoverage


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
