"""Create durable Pass 3 historical bootstrap requests without fetching inline."""

from __future__ import annotations

import argparse
import json
from datetime import date

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.workstation import Instrument
from app.services.evidence_history_service import create_historical_request
from app.services.screening_service import deep_instrument_ids


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create bounded, resumable Global Evidence history requests"
    )
    parser.add_argument(
        "--preset",
        choices=("psx_12m", "deep_company_12m", "news_90d", "all"),
        required=True,
    )
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--date-from", type=_date)
    parser.add_argument("--date-to", type=_date)
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--fetch-budget", type=int)
    parser.add_argument("--storage-budget-mb", type=int)
    args = parser.parse_args()
    presets = (
        ("psx_12m", "deep_company_12m", "news_90d")
        if args.preset == "all"
        else (args.preset,)
    )
    created: list[dict[str, object]] = []
    with SessionLocal() as db:
        for preset in presets:
            instruments: list[Instrument | None]
            if preset == "deep_company_12m":
                if args.symbol:
                    instruments = list(
                        db.scalars(
                            select(Instrument).where(
                                Instrument.symbol.in_([item.strip().upper() for item in args.symbol])
                            )
                        ).all()
                    )
                    found = {item.symbol for item in instruments if item}
                    missing = sorted(set(item.strip().upper() for item in args.symbol) - found)
                    if missing:
                        parser.error(f"Unknown instrument symbols: {', '.join(missing)}")
                else:
                    instruments = [
                        db.get(Instrument, instrument_id)
                        for instrument_id in sorted(deep_instrument_ids(db))
                    ]
            else:
                instruments = [None]
            for instrument in instruments:
                if preset == "deep_company_12m" and instrument is None:
                    continue
                row = create_historical_request(
                    db,
                    preset_key=preset,
                    instrument=instrument,
                    date_from=args.date_from,
                    date_to=args.date_to,
                    max_candidates=args.max_candidates,
                    fetch_budget=args.fetch_budget,
                    storage_budget_bytes=(
                        args.storage_budget_mb * 1024 * 1024
                        if args.storage_budget_mb
                        else None
                    ),
                )
                created.append(
                    {
                        "id": row.id,
                        "preset": row.preset_key,
                        "scope": row.scope_key,
                        "status": row.status,
                    }
                )
    print(json.dumps({"requests": created}, sort_keys=True))


if __name__ == "__main__":
    main()
