"""Manual Pass 1 runner. Automated queues and scheduling arrive in Pass 2."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.ingestion.evidence_catalog import build_pass1_registry
from app.services.evidence_pipeline import run_source_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one synchronous evidence discovery slice")
    parser.add_argument("--source", required=True, help="Configured Pass 1 source key")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 250:
        parser.error("--limit must be between 1 and 250")
    registry = build_pass1_registry()
    with SessionLocal() as db:
        result = run_source_once(db, registry.get(args.source), limit=args.limit)
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
