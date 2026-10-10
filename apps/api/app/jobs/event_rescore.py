"""Recompute classified event records (title, materiality) from their stored member statements.

No model calls and no acquisition. Safe to re-run; use after changing refresh_record rules.
    python -m app.jobs.event_rescore [--days 120]
"""
import argparse
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.workstation import NormalizedEvent
from app.services.pipeline.events import VERSION, refresh_record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=120)
    days = parser.parse_args().days
    since = datetime.now(UTC) - timedelta(days=days)
    changed = total = 0
    with SessionLocal() as db:
        ids = list(db.scalars(select(NormalizedEvent.id).where(NormalizedEvent.detection_version == VERSION,
            NormalizedEvent.classification_status == 'classified', NormalizedEvent.occurred_at >= since)))
        for event_id in ids:
            event = db.get(NormalizedEvent, event_id)
            before = (event.title, event.materiality)
            refresh_record(db, event)
            total += 1
            changed += before != (event.title, event.materiality)
            if total % 500 == 0: db.commit()
        db.commit()
    print({'rescored': total, 'changed': changed})


if __name__ == '__main__':
    main()
