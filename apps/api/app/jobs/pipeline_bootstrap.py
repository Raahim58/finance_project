"""Create disabled source targets or bounded recovery manifests; does not start workers."""
import argparse
from calendar import monthrange
from datetime import UTC, date, datetime
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.pipeline import SourceTarget
from app.models.document import Document
from app.models.workstation import DataSource, Instrument
from app.models.evidence import EvidenceSourceConfig
from app.services.pipeline.runs import enqueue
from app.services.ingestion_persistence import source


def news_start(day):
    index=day.year*12+day.month-1-18;year,zero_month=divmod(index,12);month=zero_month+1
    return date(year,month,min(day.day,monthrange(year,month)[1]))


def bootstrap(db, *, replay_limit=0, approved_sources=(), activate=False):
    from app.ingestion.evidence_catalog import SOURCE_SPECS
    from app.services.evidence_pipeline import ensure_source_config
    if set(approved_sources)-{s.key for s in SOURCE_SPECS}: raise ValueError('unknown_approved_source')
    for key in approved_sources: ensure_source_config(db,key)
    created=0
    for config in db.scalars(select(EvidenceSourceConfig)):
        existing=db.scalar(select(SourceTarget).where(SourceTarget.data_source_id==config.data_source_id,SourceTarget.scope_key=='evidence:'+config.source_key))
        if existing: continue
        db.add(SourceTarget(data_source_id=config.data_source_id,evidence_config_id=config.id,scope_key='evidence:'+config.source_key,
            adapter_key=config.source_key,schedule='announcements' if config.source_key=='psx_announcements' else 'news',enabled=False));created+=1
    official=source(db,'PSX pipeline numeric targets','market','https://dps.psx.com.pk',10,120,'Target configuration; not data provenance.')
    for instrument in db.scalars(select(Instrument).where(Instrument.instrument_type=='equity',Instrument.active_to.is_(None))):
        scope='reports:'+instrument.symbol
        if not db.scalar(select(SourceTarget.id).where(SourceTarget.data_source_id==official.id,SourceTarget.scope_key==scope)):
            db.add(SourceTarget(data_source_id=official.id,scope_key=scope,instrument_id=instrument.id,adapter_key='reports',schedule='announcements',enabled=False));created+=1
    for adapter,schedule in (('prices','prices'),('maintenance','maintenance')):
        if not db.scalar(select(SourceTarget.id).where(SourceTarget.data_source_id==official.id,SourceTarget.scope_key==adapter)):
            db.add(SourceTarget(data_source_id=official.id,scope_key=adapter,adapter_key=adapter,schedule=schedule,enabled=False));created+=1
    replayed=0
    if replay_limit:
        for doc in db.scalars(select(Document).where(Document.visibility=='public',Document.owner_user_id.is_(None),Document.portfolio_id.is_(None),
            Document.data_status=='observed').order_by(Document.published_date.desc()).limit(replay_limit)):
            stage='report_index' if doc.document_type in ('annual_report','quarterly_report','interim_report') else 'sections'
            enqueue(db,stage,'document:'+doc.id,{'document_id':doc.id,'content_hash':doc.content_hash},mode='replay');replayed+=1
    enabled=0
    if activate:
        for target in db.scalars(select(SourceTarget)):
            if target.adapter_key in approved_sources or target.adapter_key in ('prices','reports','maintenance'):
                target.enabled=True;enabled+=1
                publisher=db.get(DataSource,target.data_source_id);publisher.enabled=True
    db.commit();return {'targets_created':created,'targets_enabled':enabled,'stored_documents_queued':replayed}


def historical(db,symbol, *, price_start=None):
    instrument=db.scalar(select(Instrument).where(Instrument.symbol==symbol.upper()))
    if not instrument: raise ValueError('observed_instrument_required')
    end=date.today();start=news_start(end)
    enqueue(db,'reports','history_reports:'+instrument.id,{'symbol':instrument.symbol,'as_of':str(end)},mode='historical')
    enqueue(db,'discover','history_mettis:'+str(start),{'source_key':'mettis','archive':'mettis','date_from':str(start),'date_to':str(end),'cursor':{}},mode='historical')
    enqueue(db,'discover','history_announcements:'+instrument.id,{'source_key':'psx_announcements','cursor':{'symbol':instrument.symbol,'date_from':str(start),'date_to':str(end),'offset':0}},mode='historical')
    count=0
    if price_start:
        first=date.fromisoformat(price_start)
        first=max(first,instrument.active_from) if instrument.active_from else first
        if first>end: raise ValueError('history_start_after_end')
        cursor=first.replace(day=1)
        while cursor<=end:
            enqueue(db,'history_prices',f'history_price:{instrument.id}:{cursor}',{'symbol':instrument.symbol,'year':cursor.year,'month':cursor.month},mode='historical')
            count+=1;cursor=date(cursor.year+(cursor.month==12),1 if cursor.month==12 else cursor.month+1,1)
    db.commit();return {'symbol':symbol,'news_window':[str(start),str(end)],'price_months_queued':count,
        'price_gap':None if price_start else 'Accessible price-history start is unverified; specify --price-start from observed coverage.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-sources',default='')
    parser.add_argument('--activate',action='store_true',help='Explicitly enable reviewed targets; starts no workers')
    parser.add_argument('--replay-limit',type=int,default=0)
    parser.add_argument('--historical-symbol');parser.add_argument('--price-start')
    args=parser.parse_args()
    if not 0<=args.replay_limit<=1000: parser.error('Replay limit must be 0..1000; run bounded batches')
    with SessionLocal() as db:
        result=historical(db,args.historical_symbol,price_start=args.price_start) if args.historical_symbol else bootstrap(db,replay_limit=args.replay_limit,approved_sources=tuple(filter(None,args.approved_sources.split(','))),activate=args.activate)
        print(json.dumps(result))

if __name__=='__main__':main()
