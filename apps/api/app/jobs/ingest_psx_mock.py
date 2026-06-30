import argparse
from datetime import date

from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic mock PSX market data.")
    parser.add_argument("--days", type=int, default=365, help="Number of trading days to generate.")
    parser.add_argument("--end-date", type=date.fromisoformat, default=None, help="YYYY-MM-DD end date.")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = generate_mock_market_data(db, days=args.days, end_date=args.end_date)

    print(
        "Generated mock PSX data: "
        f"{result['companies']} companies, {result['prices']} prices, "
        f"{result['derived_stats']} snapshots/sector stats."
    )


if __name__ == "__main__":
    main()
