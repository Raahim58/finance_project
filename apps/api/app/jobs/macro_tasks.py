"""Dedicated Celery tasks for source-independent macro ingestion."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select

from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.workstation import IngestionRun, MacroObservation, MacroSeries
from app.services.macro_ingestion_service import refresh_macro_series


@celery_app.task(
    name="macro.refresh_series",
    autoretry_for=(httpx.TimeoutException, httpx.NetworkError),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=2,
)
def refresh_series(series_key: str, run_key: str) -> dict[str, object]:
    with SessionLocal() as db:
        run = db.scalar(
            select(IngestionRun).where(
                IngestionRun.job_key == "macro-series-refresh",
                IngestionRun.run_key == run_key,
            )
        )
        if run is None:
            raise ValueError("Macro ingestion run is missing")
        if run.status in {"completed", "partial"}:
            return {"series_key": series_key, "status": run.status, "idempotent": True}
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.finished_at = None
        db.commit()

        series = db.scalar(select(MacroSeries).where(MacroSeries.key == series_key))
        latest = None
        if series is not None:
            latest = db.scalar(
                select(func.max(MacroObservation.effective_date)).where(
                    MacroObservation.series_id == series.id,
                    MacroObservation.is_selected.is_(True),
                )
            )
        start = (
            latest - timedelta(days=400)
            if latest
            else date(settings.macro_history_start_year, 1, 1)
        )
        try:
            result = refresh_macro_series(db, series_key, start=start, end=date.today())
            failed = sum(item.get("status") == "failed" for item in result.diagnostics)
            run = db.get(IngestionRun, run.id)
            run.status = "partial" if failed else "completed"
            run.attempted_count = result.providers_attempted
            run.accepted_count = result.observations_written
            run.rejected_count = failed
            run.latest_observation_at = (
                datetime.combine(result.latest_observation, datetime.min.time(), tzinfo=UTC)
                if result.latest_observation
                else None
            )
            run.diagnostics_json = json.dumps({"providers": result.diagnostics}, sort_keys=True)
            run.finished_at = datetime.now(UTC)
            db.commit()
            return {"status": run.status, **asdict(result)}
        except Exception as exc:
            db.rollback()
            run = db.get(IngestionRun, run.id)
            run.status = "failed"
            run.retry_count += 1
            run.error_class = type(exc).__name__
            run.error_message = str(exc)[:2000]
            run.finished_at = datetime.now(UTC)
            db.commit()
            raise

