"""Continuously replenish bounded Phase 2 producer queues."""

import time

from redis import Redis

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.phase2_orchestration import enqueue_reconstructable_phase2_work


QUEUE_TARGETS = {
    "broad_fundamentals": settings.phase2_broad_queue_target,
    "dps_history": settings.phase2_history_queue_target,
    "financial_download": settings.phase2_download_queue_target,
    "financial_extract": settings.phase2_extract_queue_target,
}


def main() -> None:
    redis = Redis.from_url(settings.celery_broker_url)
    while True:
        try:
            limits = {
                queue: max(0, target - int(redis.llen(queue)))
                for queue, target in QUEUE_TARGETS.items()
            }
            if any(limits.values()):
                with SessionLocal() as db:
                    queued = enqueue_reconstructable_phase2_work(db, queue_limits=limits)
                print(f"Phase 2 queues replenished: {queued}", flush=True)
                if not any(queued.values()):
                    time.sleep(60)
                    continue
        except Exception as exc:
            print(f"Phase 2 queue refill failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(settings.phase2_refill_seconds)


if __name__ == "__main__":
    main()
