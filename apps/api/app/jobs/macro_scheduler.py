"""Postgres-led scheduler for canonical macro-series refresh tasks."""

from __future__ import annotations

import argparse
import json
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.jobs.macro_tasks import refresh_series
from app.services.macro_schedule_service import enqueue_due_macro_refreshes


def run_once() -> dict[str, object]:
    with SessionLocal() as db:
        result = enqueue_due_macro_refreshes(
            db,
            publish=lambda series_key, run_key: refresh_series.apply_async(
                args=(series_key, run_key), queue="macro", priority=3
            ),
        )
    payload = result.__dict__.copy()
    payload["run_ids"] = list(result.run_ids)
    if result.status == "disabled":
        payload["setting"] = "MACRO_INGESTION_ENABLED"
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dedicated canonical macro scheduler")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        print(json.dumps(run_once(), sort_keys=True), flush=True)
        if args.once:
            return
        time.sleep(settings.macro_scheduler_seconds)


if __name__ == "__main__":
    main()
