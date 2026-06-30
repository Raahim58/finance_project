import argparse
from datetime import date

from app.db.session import SessionLocal
from app.services.market_ingestion import compute_market_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute market snapshots and sector stats.")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="Optional YYYY-MM-DD date.")
    parser.add_argument("--source", default="mock", help="Market data source to compute.")
    args = parser.parse_args()

    with SessionLocal() as db:
        count = compute_market_stats(db, source=args.source, target_date=args.date)

    print(f"Computed {count} market snapshot/sector-stat rows.")


if __name__ == "__main__":
    main()
