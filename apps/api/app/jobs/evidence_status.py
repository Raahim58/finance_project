"""Print Postgres-backed evidence funnel progress and Celery queue depths."""

from __future__ import annotations

import argparse
import json
import time

import redis

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.evidence_scheduler_service import evidence_operational_status

QUEUES = (
    "evidence_discovery",
    "evidence_fetch",
    "evidence_parse",
    "evidence_pdf",
    "evidence_index",
    "historical_hydrate",
)


def snapshot() -> dict[str, object]:
    with SessionLocal() as db:
        payload = evidence_operational_status(db)
    try:
        broker = redis.Redis.from_url(settings.celery_broker_url)
        payload["celery_queue_depths"] = {queue: int(broker.llen(queue)) for queue in QUEUES}
    except redis.RedisError as exc:
        payload["celery_queue_depths"] = {"error": f"{type(exc).__name__}: {exc}"}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Show evidence ingestion funnel and queue status")
    parser.add_argument("--watch", type=int, metavar="SECONDS")
    args = parser.parse_args()
    if args.watch is not None and args.watch < 2:
        parser.error("--watch must be at least 2 seconds")
    while True:
        print(json.dumps(snapshot(), sort_keys=True, default=str), flush=True)
        if args.watch is None:
            return
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
