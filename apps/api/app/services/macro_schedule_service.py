"""Reusable durable macro scheduling used by the scheduler and context coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.macro_catalog import MACRO_SERIES
from app.jobs.macro_tasks import refresh_series
from app.models.workstation import IngestionRun
from app.services.macro_ingestion_service import ensure_macro_catalog


@dataclass(frozen=True)
class MacroScheduleResult:
    status: str
    run_ids: tuple[str, ...]
    queued: int
    active: int
    catalog_series_created: int
    catalog_providers_created: int


def enqueue_due_macro_refreshes(
    db: Session,
    *,
    now: datetime | None = None,
    publish: Callable[[str, str], None] | None = None,
) -> MacroScheduleResult:
    if not settings.macro_ingestion_enabled:
        return MacroScheduleResult("disabled", (), 0, 0, 0, 0)
    now = now or datetime.now(UTC)
    publish = publish or (
        lambda series_key, run_key: refresh_series.apply_async(
            args=(series_key, run_key), queue="macro", priority=3
        )
    )
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
    period = now.date().isoformat()
    linked: list[str] = []
    queued = 0
    for spec in MACRO_SERIES:
        run_key = f"{spec.key}:{period}"
        run = db.scalar(select(IngestionRun).where(
            IngestionRun.job_key == "macro-series-refresh",
            IngestionRun.run_key == run_key,
        ))
        if run and run.status in {"queued", "running", "completed", "partial"}:
            linked.append(run.id)
            continue
        if queued >= capacity or (run and run.status == "failed" and run.retry_count >= 3):
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
        linked.append(run.id)
        try:
            publish(spec.key, run_key)
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
    return MacroScheduleResult(
        "running", tuple(linked), queued, remaining, created_series, created_providers
    )
