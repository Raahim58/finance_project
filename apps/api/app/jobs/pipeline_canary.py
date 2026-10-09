"""Configure a bounded production cohort; scheduler/worker startup is explicit."""
import argparse,json
from uuid import uuid4
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.pipeline import SourceTarget
from app.models.workstation import Instrument
from app.services.evidence_pipeline import ensure_source_config
from app.services.ingestion_persistence import source


def configure(db, *, symbols=('LUCK','FFC'),news_limit=10,report_limit=1):
    if not 1<=news_limit<=10 or not 1<=report_limit<=2: raise ValueError('bounded_canary_limits_required')
    batch=str(uuid4());insts=list(db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols))))
    if len(insts)!=len(symbols): raise ValueError('observed_canary_companies_missing')
    if db.scalar(select(SourceTarget.id).where(SourceTarget.enabled.is_(True))):
        raise ValueError('enabled_targets_exist_use_existing_canary_or_review_scope')
    news,config,_=ensure_source_config(db,'mettis');news.enabled=True
    numeric=source(db,'PSX pipeline numeric targets','market','https://dps.psx.com.pk',10,120,'Target configuration; not data provenance.')
    targets=[SourceTarget(data_source_id=news.id,evidence_config_id=config.id,scope_key='canary:'+batch+':news',
        adapter_key='mettis',schedule='news',enabled=True,cursor={'canary_batch':batch,'news_limit':news_limit})]
    for inst in insts:
        targets.append(SourceTarget(data_source_id=numeric.id,instrument_id=inst.id,scope_key='canary:'+batch+':reports:'+inst.symbol,
            adapter_key='reports',schedule='announcements',enabled=True,cursor={'canary_batch':batch,'report_limit':report_limit}))
    targets.append(SourceTarget(data_source_id=numeric.id,scope_key='canary:'+batch+':prices',adapter_key='prices',schedule='prices',
        enabled=True,cursor={'canary_batch':batch,'symbols':list(symbols)}))
    db.add_all(targets);db.commit()
    return {'batch_id':batch,'symbols':list(symbols),'news_per_slot':news_limit,'reports_per_company_per_day':report_limit,
        'target_ids':[t.id for t in targets],'schedulers_started':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--symbols',nargs='+',default=['LUCK','FFC'])
    parser.add_argument('--news-limit',type=int,default=10);parser.add_argument('--report-limit',type=int,default=1)
    args=parser.parse_args()
    with SessionLocal() as db: print(json.dumps(configure(db,symbols=tuple(args.symbols),news_limit=args.news_limit,report_limit=args.report_limit)))

if __name__=='__main__':main()
