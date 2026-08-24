"""Backfill or incrementally normalize retained raw evidence events."""

import argparse
import json

from app.db.session import SessionLocal
from app.services.event_intelligence_service import normalize_pending_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize retained announcements and news into Phase 6 events")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--all", action="store_true", help="Continue in batches until no pending events remain")
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    totals = {"scanned": 0, "classified": 0, "unclassified": 0}
    while True:
        with SessionLocal() as db:
            result = normalize_pending_events(db, limit=args.limit)
        for key in totals:
            totals[key] += result[key]
        print(json.dumps({"batch": result, "totals": totals}, sort_keys=True), flush=True)
        if not args.all or result["scanned"] == 0:
            break


if __name__ == "__main__":
    main()
