"""Continuously replenish bounded Phase 2 producer queues."""

import time

from redis import Redis

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.phase2_orchestration import enqueue_reconstructable_phase2_work


PRODUCER_QUEUES = ("broad_fundamentals", "dps_history", "financial_download")


def main() -> None:
    redis = Redis.from_url(settings.celery_broker_url)
    while True:
        try:
            # Refill only after the prior producer batch has drained. Active tasks
            # are already marked running in Postgres and are not reconstructed.
            if sum(int(redis.llen(queue)) for queue in PRODUCER_QUEUES) == 0:
                with SessionLocal() as db:
                    queued = enqueue_reconstructable_phase2_work(db, limit=500)
                print(f"Phase 2 queues replenished: {queued}", flush=True)
                if not any(queued.values()):
                    time.sleep(60)
                    continue
        except Exception as exc:
            print(f"Phase 2 queue refill failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(settings.phase2_refill_seconds)


if __name__ == "__main__":
    main()
