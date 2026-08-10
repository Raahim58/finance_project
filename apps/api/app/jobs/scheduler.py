import argparse
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.market_ingestion import run_market_data_cycle
from app.models.user import User
from app.models.workstation import MonitoringRule
from app.services.monitoring_service import run_monitoring
from app.services.ledger_service import apply_recorded_corporate_actions, generate_daily_snapshots
from app.services.ingestion_service import bootstrap_next_market_history, run_due_ingestion_jobs
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
        corporate_actions = apply_recorded_corporate_actions(db)
        snapshot_count = generate_daily_snapshots(db)
        history_run = bootstrap_next_market_history(db) if run.status == "success" else None
        background_runs = run_due_ingestion_jobs(db) if run.status == "success" else []
        monitoring_runs = run_monitoring_jobs(db)
    print(
        "Market scheduler run finished with "
        f"status={run.status} mode={run.mode} attempted_provider={run.attempted_provider} "
        f"used_provider={run.used_provider} latest_trade_date={run.latest_trade_date}"
        f" portfolio_snapshots={snapshot_count} monitoring_runs={monitoring_runs}"
        f" history_run={history_run.id if history_run else None}"
        f" background_jobs={len(background_runs)}"
        f" corporate_actions={corporate_actions['applied']}"
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
