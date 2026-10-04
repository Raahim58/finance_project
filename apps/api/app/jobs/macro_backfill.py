"""Explicit, sequential canonical macro imports with durable execution accounting."""

import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.macro_catalog import MACRO_SERIES_BY_KEY
from app.models.workstation import IngestionRun
from app.services.macro_ingestion_service import refresh_macro_series


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--series', action='append', required=True, choices=sorted(MACRO_SERIES_BY_KEY))
    parser.add_argument('--date-from', type=date.fromisoformat, required=True)
    parser.add_argument('--date-to', type=date.fromisoformat,
        default=datetime.now(ZoneInfo('Asia/Karachi')).date())
    args = parser.parse_args()
    if args.date_from > args.date_to:
        parser.error('date-from must not exceed date-to')
    failed = 0
    for key in dict.fromkeys(args.series):
        with SessionLocal() as db:
            run_key = f'{key}:{args.date_from}:{args.date_to}'
            run = db.scalar(select(IngestionRun).where(
                IngestionRun.job_key == 'macro-series-backfill', IngestionRun.run_key == run_key))
            if run is None:
                run = IngestionRun(job_key='macro-series-backfill', run_key=run_key, provider='provider_ladder')
                db.add(run)
            run.status = 'running'
            run.started_at = datetime.now(UTC)
            run.finished_at = None
            run.error_class = run.error_message = None
            db.commit()
            try:
                result = refresh_macro_series(db, key, start=args.date_from, end=args.date_to)
                run.status = 'partial' if any(d.get('status') == 'failed' for d in result.diagnostics) else 'completed'
                run.attempted_count = result.providers_attempted
                run.accepted_count = result.observations_written
                run.rejected_count = sum(d.get('status') == 'failed' for d in result.diagnostics)
                run.diagnostics_json = json.dumps(asdict(result), default=str, sort_keys=True)
                run.latest_observation_at = datetime.combine(result.latest_observation, datetime.min.time(), tzinfo=UTC) if result.latest_observation else None
                print(json.dumps({'status': run.status, **asdict(result)}, default=str), flush=True)
            except Exception as exc:
                db.rollback()
                run = db.get(IngestionRun, run.id)
                run.status = 'failed'
                run.error_class = type(exc).__name__
                run.error_message = str(exc)[:2000]
                failed += 1
                print(json.dumps({'series_key': key, 'status': 'failed', 'error_class': run.error_class, 'error': run.error_message}), flush=True)
            run.finished_at = datetime.now(UTC)
            db.commit()
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
