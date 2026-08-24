"""Backfill or incrementally normalize retained raw evidence events."""

import argparse
import json

from app.db.session import SessionLocal
from app.services.event_intelligence_service import normalize_pending_events, rebuild_normalized_event_cache


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize retained announcements and news into Phase 6 events")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--all", action="store_true", help="Continue in batches until no pending events remain")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the reproducible normalized-event cache")
    parser.add_argument("--confirm-rebuild", action="store_true", help="Confirm deletion of derived Phase 6 rows")
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.rebuild and not args.confirm_rebuild:
        raise SystemExit("--rebuild requires --confirm-rebuild")
    if args.rebuild:
        with SessionLocal() as db:
            removed = rebuild_normalized_event_cache(db)
        print(json.dumps({"rebuild_removed": removed}, sort_keys=True), flush=True)
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
