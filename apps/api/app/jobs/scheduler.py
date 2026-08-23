import argparse
import time
from datetime import UTC, datetime

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.market_ingestion import run_market_data_cycle
from app.models.user import User
from app.models.workstation import MonitoringRule
from app.services.monitoring_service import run_monitoring
from app.services.ledger_service import apply_recorded_corporate_actions, generate_daily_snapshots
from app.services.ingestion_service import run_due_ingestion_jobs
from app.services.ingestion_run_service import fail_ingestion_run, finish_ingestion_run, start_ingestion_run
from app.services.screening_service import compute_screening_snapshots
from sqlalchemy import select


def run_monitoring_jobs(db) -> int:
    pairs = db.execute(select(MonitoringRule.user_id, MonitoringRule.portfolio_id).where(MonitoringRule.enabled.is_(True)).distinct()).all()
    completed = 0
    for user_id, portfolio_id in pairs:
        user = db.get(User, user_id)
        if user is None:
            continue
        try:
            run_monitoring(db, user, portfolio_id); completed += 1
        except Exception:
            db.rollback()
    return completed


def run_once() -> None:
    with SessionLocal() as db:
        run = run_market_data_cycle(db, settings.market_data_mode)
        health_run, reused = start_ingestion_run(
            db,
            job_key=f"refresh:{settings.market_data_mode}",
            run_key=f"scheduler:{run.started_at.isoformat() if getattr(run, 'started_at', None) else datetime.now(UTC).isoformat()}",
            provider=settings.market_data_mode,
        )
        if not reused:
            if run.status == "failed":
                fail_ingestion_run(db, health_run.id, RuntimeError(run.message or "Market-price ingestion failed"))
            else:
                latest = datetime.combine(run.latest_trade_date, datetime.min.time(), tzinfo=UTC) if run.latest_trade_date else None
                finish_ingestion_run(db, health_run, {"attempted": getattr(run, "attempted_count", getattr(run, "records_written", 0)), "accepted": getattr(run, "accepted_count", getattr(run, "records_written", 0)), "rejected": getattr(run, "rejected_count", 0), "latest_observation_at": latest, "diagnostics": {"attempted_provider": run.attempted_provider, "used_provider": run.used_provider}})
        corporate_actions = apply_recorded_corporate_actions(db)
        snapshot_count = generate_daily_snapshots(db)
        screening_count = len(compute_screening_snapshots(db)) if run.status == "success" and settings.market_data_mode != "mock" else 0
        # Research and macro providers are independent of the market-price job.
        # Each provider records its own terminal state inside run_due_ingestion_jobs.
        background_runs = run_due_ingestion_jobs(db)
        monitoring_runs = run_monitoring_jobs(db)
    print(
        "Market scheduler run finished with "
        f"status={run.status} mode={run.mode} attempted_provider={run.attempted_provider} "
        f"used_provider={run.used_provider} latest_trade_date={run.latest_trade_date}"
        f" portfolio_snapshots={snapshot_count} monitoring_runs={monitoring_runs}"
        f" background_jobs={len(background_runs)}"
        f" corporate_actions={corporate_actions['applied']}"
        f" screening_snapshots={screening_count}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run periodic market data refresh jobs.")
    parser.add_argument("--once", action="store_true", help="Run one refresh cycle and exit.")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    while True:
        run_once()
        time.sleep(settings.market_data_refresh_seconds)


if __name__ == "__main__":
    main()
