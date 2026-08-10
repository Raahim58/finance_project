import argparse
from datetime import date

from app.db.session import SessionLocal
from app.services.ingestion_service import historical_gaps, run_historical_backfill


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotent historical PSX market-data backfill and gap audit")
    parser.add_argument("--provider", default="dps", choices=["dps", "yahoo", "psxdata", "auto"])
    parser.add_argument("--symbols", required=True, help="Comma-separated PSX symbols")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", default=date.today().isoformat(), type=date.fromisoformat)
    parser.add_argument("--gaps-only", action="store_true")
    args = parser.parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    with SessionLocal() as db:
        if args.gaps_only:
            for symbol in symbols:
                print(historical_gaps(db, symbol, args.start, args.end))
            return
        run = run_historical_backfill(
            db,
            provider_name=args.provider,
            symbols=symbols,
            start=args.start,
            end=args.end,
        )
        print({
            "run_id": run.id,
            "status": run.status,
            "attempted": run.attempted_count,
            "accepted": run.accepted_count,
            "rejected": run.rejected_count,
            "error": run.error_message,
        })


if __name__ == "__main__":
    main()
