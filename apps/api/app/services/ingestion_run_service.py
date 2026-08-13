import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workstation import IngestionRun


TERMINAL_SUCCESS_STATUSES = {"success", "partial", "completed"}


def start_ingestion_run(
    db: Session,
    *,
    job_key: str,
    run_key: str,
    provider: str,
) -> tuple[IngestionRun, bool]:
    existing = db.scalar(
        select(IngestionRun).where(IngestionRun.job_key == job_key, IngestionRun.run_key == run_key)
    )
    if existing and existing.status in {"running", *TERMINAL_SUCCESS_STATUSES}:
        return existing, True
    if existing:
        run = existing
        run.status = "running"
        run.retry_count += 1
        run.error_class = None
        run.error_message = None
        run.diagnostics_json = "{}"
        run.started_at = datetime.now(UTC)
        run.finished_at = None
        run.latest_observation_at = None
        run.attempted_count = 0
        run.accepted_count = 0
        run.updated_count = 0
        run.rejected_count = 0
    else:
        run = IngestionRun(job_key=job_key, run_key=run_key, provider=provider, status="running")
        db.add(run)
    db.commit()
    db.refresh(run)
    return run, False


def finish_ingestion_run(
    db: Session,
    run: IngestionRun,
    result: dict[str, object],
) -> IngestionRun:
    run.attempted_count = int(result.get("attempted", 0))
    run.accepted_count = int(result.get("accepted", 0))
    run.updated_count = int(result.get("updated", 0))
    run.rejected_count = int(result.get("rejected", 0))
    run.latest_observation_at = result.get("latest_observation_at")  # type: ignore[assignment]
    diagnostics = result.get("diagnostics") or {}
    run.diagnostics_json = json.dumps(diagnostics, default=str, sort_keys=True)
    if run.rejected_count and (run.accepted_count or run.updated_count):
        run.status = "partial"
    elif run.rejected_count and not (run.accepted_count or run.updated_count):
        run.status = "failed"
    else:
        run.status = "success"
    errors = diagnostics.get("errors", []) if isinstance(diagnostics, dict) else []
    if errors:
        run.error_message = "; ".join(str(error) for error in errors)[:2000]
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def fail_ingestion_run(db: Session, run_id: str, exc: Exception) -> IngestionRun:
    db.rollback()
    run = db.get(IngestionRun, run_id)
    if run is None:
        raise RuntimeError(f"Ingestion run {run_id} disappeared while recording a failure") from exc
    run.status = "failed"
    run.error_class = type(exc).__name__
    run.error_message = str(exc)[:2000]
    run.diagnostics_json = json.dumps({"errors": [str(exc)[:1000]]})
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run
