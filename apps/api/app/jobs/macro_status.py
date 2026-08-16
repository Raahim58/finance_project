"""Read-only status for canonical macro ingestion."""

from __future__ import annotations

import json

import redis
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.workstation import IngestionRun, MacroObservation, MacroSeries, MacroSeriesProvider


def main() -> None:
    with SessionLocal() as db:
        latest_runs = list(
            db.scalars(
                select(IngestionRun)
                .where(IngestionRun.job_key == "macro-series-refresh")
                .order_by(IngestionRun.started_at.desc())
                .limit(30)
            )
        )
        payload = {
            "series": db.scalar(select(func.count()).select_from(MacroSeries)) or 0,
            "providers": db.scalar(select(func.count()).select_from(MacroSeriesProvider)) or 0,
            "observations": db.scalar(select(func.count()).select_from(MacroObservation)) or 0,
            "selected_observations": db.scalar(
                select(func.count()).select_from(MacroObservation).where(
                    MacroObservation.is_selected.is_(True)
                )
            ) or 0,
            "runs": dict(
                db.execute(
                    select(IngestionRun.status, func.count())
                    .where(IngestionRun.job_key == "macro-series-refresh")
                    .group_by(IngestionRun.status)
                ).all()
            ),
            "provider_contracts": {
                "enabled": db.scalar(
                    select(func.count()).select_from(MacroSeriesProvider).where(
                        MacroSeriesProvider.enabled.is_(True)
                    )
                )
                or 0,
                "disabled": db.scalar(
                    select(func.count()).select_from(MacroSeriesProvider).where(
                        MacroSeriesProvider.enabled.is_(False)
                    )
                )
                or 0,
            },
            "latest_runs": [
                {
                    "series_key": run.run_key.rsplit(":", 1)[0],
                    "status": run.status,
                    "attempted_providers": run.attempted_count,
                    "observations_written": run.accepted_count,
                    "provider_failures": run.rejected_count,
                    "retry_count": run.retry_count,
                    "latest_observation": run.latest_observation_at,
                    "error": run.error_message,
                    "diagnostics": json.loads(run.diagnostics_json or "{}"),
                }
                for run in latest_runs
            ],
            "latest_by_series": [
                {"series_key": key, "latest": latest, "selected": count}
                for key, latest, count in db.execute(
                    select(
                        MacroSeries.key,
                        func.max(MacroObservation.effective_date),
                        func.count(MacroObservation.id),
                    )
                    .outerjoin(
                        MacroObservation,
                        (MacroObservation.series_id == MacroSeries.id)
                        & (MacroObservation.is_selected.is_(True)),
                    )
                    .group_by(MacroSeries.key)
                    .order_by(MacroSeries.key)
                ).all()
            ],
        }
    try:
        payload["queue_depth"] = redis.Redis.from_url(settings.celery_broker_url).llen("macro")
    except redis.RedisError as exc:
        payload["queue_depth"] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(payload, sort_keys=True, default=str), flush=True)


if __name__ == "__main__":
    main()
