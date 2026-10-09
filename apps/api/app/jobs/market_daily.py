"""Bounded EOD ingestion only: no model calls, research jobs or portfolio writes."""
import argparse
import json
import time
from datetime import UTC, datetime, time as wall_time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.db.session import SessionLocal, engine
from app.models.workstation import IngestionRun
from app.services.corporate_action_ingestion import import_payout_page
from app.services.dps_capitalization import import_capitalization
from app.services.index_ingestion import INDEXES, import_index_month
from app.services.market_providers import DpsMarketDataProvider

KARACHI = ZoneInfo('Asia/Karachi')
RETRY_SECONDS = 7200


def target_day(now):
    now = now.astimezone(KARACHI)
    day = now.date() if now.time() >= wall_time(18, 15) else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def recent_weekdays(day, count=5):
    days = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days


def run_stage(key, day, operation, *, force=False):
    """Persist each stage independently; a failed lane cannot undo another."""
    now = datetime.now(UTC)
    with SessionLocal() as db:
        run = db.scalar(select(IngestionRun).where(
            IngestionRun.job_key == 'dps-market-daily:' + key,
            IngestionRun.run_key == str(day)))
        if run and not force:
            if run.status == 'completed':
                return {**json.loads(run.diagnostics_json or '{}'), 'stage': key, 'date': str(day), 'status': 'already_completed'}
            previous = run.finished_at or run.started_at
            if previous and (now - previous.replace(tzinfo=UTC)).total_seconds() < RETRY_SECONDS:
                return {'stage': key, 'date': str(day), 'status': 'retry_wait'}
        if run is None:
            run = IngestionRun(job_key='dps-market-daily:' + key, run_key=str(day), provider='dps', status='running')
            db.add(run)
        else:
            run.retry_count += 1
        run.status = 'running'; run.started_at = now; run.finished_at = None
        run.error_class = run.error_message = None
        db.commit(); run_id = run.id
        try:
            result = operation(db)
            run.status = 'completed'
            run.accepted_count = result.get('accepted', result.get('matched', result.get('records', result.get('rows', 0))))
            rejected = result.get('rejected', 0)
            run.rejected_count = len(rejected) if isinstance(rejected, list) else rejected
            run.attempted_count = result.get('attempted', run.accepted_count + run.rejected_count)
            run.diagnostics_json = json.dumps(result, default=str)
            run.finished_at = datetime.now(UTC); db.commit()
            return {'stage': key, 'date': str(day), 'status': 'completed', **result}
        except Exception as exc:
            db.rollback(); run = db.get(IngestionRun, run_id)
            run.status = 'failed'; run.error_class = type(exc).__name__
            run.error_message = str(exc)[:1000]; run.finished_at = datetime.now(UTC); db.commit()
            return {'stage': key, 'date': str(day), 'status': 'failed', 'error': run.error_message}


def run_once(*, force=False, payouts_backfill=False):
    # Dedicated connection owns the session lock across stage commits. Never
    # leave a session advisory lock on a pooled ORM connection.
    with engine.connect() as coordination:
        postgres = engine.dialect.name == 'postgresql'
        if postgres and not coordination.scalar(text("SELECT pg_try_advisory_lock(hashtext('dps-market-daily'))")):
            return [{'status': 'another_worker_running'}]
        try:
            day = target_day(datetime.now(UTC))
            results = []
            for price_day in recent_weekdays(day):
                result = run_stage('prices', price_day,
                    lambda db, d=price_day: DpsMarketDataProvider().refresh_latest(db, target_date=d), force=force)
                results.append(result); print(json.dumps(result, default=str), flush=True)
            with DpsMarketDataProvider()._client() as client:
                for symbol in INDEXES:
                    result = run_stage('index:' + symbol, day,
                        lambda db, s=symbol: import_index_month(db, s, day.replace(day=1), client), force=force)
                    results.append(result); print(json.dumps(result, default=str), flush=True)
                result = run_stage('capitalization', day,
                    lambda db: import_capitalization(db, client, day), force=force)
                results.append(result); print(json.dumps(result, default=str), flush=True)
                offset = 0
                while offset is not None:
                    result = run_stage('payouts:' + str(offset), day,
                        lambda db, o=offset: import_payout_page(db, client, o), force=force)
                    results.append(result); print(json.dumps(result, default=str), flush=True)
                    if not payouts_backfill or result['status'] not in ('completed', 'already_completed'):
                        break
                    offset = result.get('next_offset')
                    if offset is not None and offset >= 10000:
                        raise RuntimeError('Payout backfill exceeded 10,000 source rows; inspect before expanding')
                    time.sleep(0.5)
            return results
        finally:
            if postgres:
                coordination.execute(text("SELECT pg_advisory_unlock(hashtext('dps-market-daily'))"))


def main():
    from app.core.config import settings
    if settings.pipeline_enabled:
        print('{"status":"disabled","reason":"pipeline_scheduler_owns_ingestion"}')
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--force', action='store_true', help='Explicit revalidation of completed dates')
    parser.add_argument('--payouts-backfill', action='store_true', help='Read the bounded available payout archive')
    args = parser.parse_args()
    if (args.force or args.payouts_backfill) and not args.once:
        parser.error('Backfill and force require --once')
    if args.once:
        results = run_once(force=args.force, payouts_backfill=args.payouts_backfill)
        raise SystemExit(1 if any(r.get('status') == 'failed' for r in results) else 0)
    while True:
        try:
            run_once()
        except Exception as exc:
            print(json.dumps({'status': 'scheduler_error', 'error': str(exc)[:1000]}), flush=True)
        time.sleep(600)


if __name__ == '__main__':
    main()
