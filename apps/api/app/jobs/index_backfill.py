"""Resumable, sequential DPS index history. No invented index construction."""
import argparse
import json
import time
from datetime import date,datetime,UTC
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.workstation import IngestionRun
from app.services.market_providers import DpsMarketDataProvider
from app.services.index_ingestion import INDEXES,import_index_month


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',action='append',choices=sorted(INDEXES),required=True)
    parser.add_argument('--date-from',type=date.fromisoformat,required=True)
    parser.add_argument('--date-to',type=date.fromisoformat,default=date.today())
    args=parser.parse_args()
    if args.date_from>args.date_to: parser.error('Invalid date range')
    with DpsMarketDataProvider()._client() as client:
        for symbol in dict.fromkeys(args.symbol):
            month=args.date_from.replace(day=1)
            while month<=args.date_to:
                key=f'{symbol}:{month:%Y-%m}'
                with SessionLocal() as db:
                    run=db.scalar(select(IngestionRun).where(IngestionRun.job_key=='dps-index-month',IngestionRun.run_key==key))
                    # Current month is refreshed; closed months resume without refetching.
                    if run and run.status=='completed' and month<date.today().replace(day=1):
                        month=date(month.year+(month.month==12),1 if month.month==12 else month.month+1,1);continue
                    if run is None:
                        run=IngestionRun(job_key='dps-index-month',run_key=key,provider='dps');db.add(run)
                    run.status='running';run.error_class=run.error_message=None;run.started_at=datetime.now(UTC);db.commit();run_id=run.id
                    try:
                        result=import_index_month(db,symbol,month,client)
                        run.status='completed';run.accepted_count=result['rows'];run.diagnostics_json=json.dumps(result);run.finished_at=datetime.now(UTC);db.commit()
                        print(json.dumps(result),flush=True)
                    except Exception as exc:
                        db.rollback();run=db.get(IngestionRun,run_id);run.status='failed';run.error_class=type(exc).__name__;run.error_message=str(exc)[:500];run.finished_at=datetime.now(UTC);db.commit()
                        raise
                month=date(month.year+(month.month==12),1 if month.month==12 else month.month+1,1)
                time.sleep(0.5)


if __name__=='__main__':main()
