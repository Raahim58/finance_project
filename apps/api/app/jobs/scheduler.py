import argparse
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.market_ingestion import run_market_data_cycle


def run_once() -> None:
    with SessionLocal() as db:
        run = run_market_data_cycle(db, settings.market_data_mode)
    print(
        f"Market scheduler run finished with status={run.status} mode={run.mode} source={run.source} latest_trade_date={run.latest_trade_date}"
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
