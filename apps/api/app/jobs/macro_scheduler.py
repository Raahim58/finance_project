"""Postgres-led scheduler for canonical macro-series refresh tasks."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.macro_catalog import MACRO_SERIES
from app.jobs.macro_tasks import refresh_series
from app.models.workstation import IngestionRun
from app.services.macro_ingestion_service import ensure_macro_catalog


def run_once() -> dict[str, object]:
    if not settings.macro_ingestion_enabled:
        return {"status": "disabled", "setting": "MACRO_INGESTION_ENABLED", "queued": 0}
    now = datetime.now(UTC)
    period = date.today().isoformat()
    queued = 0
    with SessionLocal() as db:
        created_series, created_providers = ensure_macro_catalog(db)
        stale = now - timedelta(hours=2)
        for run in db.scalars(
            select(IngestionRun).where(
                IngestionRun.job_key == "macro-series-refresh",
                IngestionRun.status.in_(("queued", "running")),
                IngestionRun.started_at <= stale,
            )
        ):
            run.status = "failed"
            run.error_class = "StaleMacroLease"
            run.error_message = "Macro task did not finish within two hours"
            run.finished_at = now
        db.commit()
        active = db.scalar(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.job_key == "macro-series-refresh",
                IngestionRun.status.in_(("queued", "running")),
            )
        ) or 0
        capacity = max(0, settings.macro_queue_target - active)
        for spec in MACRO_SERIES:
            if queued >= capacity:
                break
            run_key = f"{spec.key}:{period}"
            run = db.scalar(
                select(IngestionRun).where(
                    IngestionRun.job_key == "macro-series-refresh",
                    IngestionRun.run_key == run_key,
                )
            )
            if run and run.status in {"queued", "running", "completed", "partial"}:
                continue
            if run and run.status == "failed" and run.retry_count >= 3:
                continue
            if run is None:
                run = IngestionRun(
                    job_key="macro-series-refresh",
                    run_key=run_key,
                    provider="provider_ladder",
                    status="queued",
                )
                db.add(run)
            else:
                run.status = "queued"
                run.error_class = None
                run.error_message = None
                run.finished_at = None
            db.commit()
            try:
                refresh_series.apply_async(args=(spec.key, run_key), queue="macro", priority=3)
                queued += 1
            except Exception as exc:
                run.status = "failed"
                run.error_class = type(exc).__name__
                run.error_message = str(exc)[:2000]
                run.finished_at = datetime.now(UTC)
                db.commit()
        remaining = db.scalar(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.job_key == "macro-series-refresh",
                IngestionRun.status.in_(("queued", "running")),
            )
        ) or 0
    return {
        "status": "running",
        "queued": queued,
        "active": remaining,
        "catalog_series_created": created_series,
        "catalog_providers_created": created_providers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dedicated canonical macro scheduler")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        print(json.dumps(run_once(), sort_keys=True), flush=True)
        if args.once:
            return
        time.sleep(settings.macro_scheduler_seconds)


if __name__ == "__main__":
    main()
