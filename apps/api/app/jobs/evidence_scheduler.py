"""Dedicated Phase 3 scheduler; it never produces Phase 2 queue work."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.evidence_scheduler_service import run_evidence_scheduler_once


def run_once() -> None:
    if not settings.evidence_enabled:
        print('{"status":"disabled","setting":"EVIDENCE_ENABLED"}')
        return
    with SessionLocal() as db:
        result = run_evidence_scheduler_once(db)
    print(json.dumps(asdict(result), sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dedicated Global Evidence scheduler")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    while True:
        run_once()
        time.sleep(settings.evidence_scheduler_seconds)


if __name__ == "__main__":
    main()
