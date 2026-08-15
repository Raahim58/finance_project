"""Inspect or apply narrowly scoped evidence-record repairs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.evidence_repair_service import repair_psx_role_slot_collisions


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit or repair known evidence classification defects")
    parser.add_argument("--repair", choices=("psx-role-slot-collisions",), required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--apply", action="store_true", help="Commit changes; otherwise perform a dry run")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    with SessionLocal() as db:
        result = repair_psx_role_slot_collisions(db, apply=args.apply, limit=args.limit)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"applied": args.apply, **asdict(result)}, sort_keys=True))


if __name__ == "__main__":
    main()
