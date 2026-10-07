"""Single-owner DB dispatcher, source cadence, and recovery. Run only after gates."""
import argparse
from datetime import UTC, datetime
import json
import time
from sqlalchemy import select, text
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.pipeline import SourceTarget
from app.models.evidence import DiscoveryCandidate,EvidenceSourceConfig
from app.models.document import Document
from app.models.workstation import DataSource, Instrument, EventSource
from app.services.pipeline.runs import enqueue,recover,dispatch
from app.services.pipeline.scheduling import scheduled_bucket
from app.jobs.pipeline_tasks import execute,QUEUES


def schedule_sources(db,now):
    count=0
    targets=db.scalars(select(SourceTarget).join(DataSource,DataSource.id==SourceTarget.data_source_id)
        .where(SourceTarget.enabled.is_(True),DataSource.enabled.is_(True)).with_for_update(skip_locked=True)).all()
    for target in targets:
        bucket=scheduled_bucket(target.schedule,now,db)
        if not bucket or target.cursor.get('last_bucket')==bucket: continue
        payload={'target_id':target.id,'bucket':bucket}
        for key in ('canary_batch','news_limit','report_limit','symbols'):
            if key in target.cursor: payload[key]=target.cursor[key]
        if target.adapter_key=='prices': stage='prices'
        elif target.adapter_key=='maintenance': stage='maintenance'
        elif target.adapter_key=='briefing': stage='briefing'
        elif target.adapter_key=='reports':
            instrument=db.get(Instrument,target.instrument_id)
            if not instrument: continue
            stage='reports';payload['symbol']=instrument.symbol
        else:
            stage='discover';payload['source_key']=target.adapter_key
            if target.adapter_key=='tavily':
                if not target.cursor.get('query') or not target.cursor.get('domains'): continue
                payload.update(query=target.cursor['query'],domains=target.cursor['domains'])
            if target.adapter_key=='mettis': payload['archive']='mettis';payload['cursor']={}
        subject='target:'+target.id+':'+bucket
        if payload.get('canary_batch'): subject='canary:'+payload['canary_batch']+':'+subject
        enqueue(db,stage,subject,payload)
        target.cursor={**target.cursor,'last_bucket':bucket};count+=1
    db.commit();return count


def reconstruct(db,limit=100):
    count=0
    # Recovery uses existing candidate state; no new source/network polling.
    rows=db.scalars(select(DiscoveryCandidate).join(EvidenceSourceConfig,EvidenceSourceConfig.id==DiscoveryCandidate.source_config_id)
        .join(DataSource,DataSource.id==EvidenceSourceConfig.data_source_id)
        .where(DataSource.enabled.is_(True),DiscoveryCandidate.source_config_id.in_(select(SourceTarget.evidence_config_id).where(SourceTarget.enabled.is_(True))),DiscoveryCandidate.status.in_(('fetch_ready','evaluating','clustered')))
        .order_by(DiscoveryCandidate.discovered_at).limit(limit)).all()
    for row in rows:
        meta=json.loads(row.metadata_json or '{}');state=meta.get('_pipeline',{})
        stage='fetch' if row.status=='fetch_ready' else 'parse' if state.get('stage')=='raw_ready' else 'index' if row.status=='clustered' else None
        if not stage: continue
        enqueue(db,stage,'candidate:'+row.id,{'candidate_id':row.id,'revision':meta.get('pipeline_revision',0)},mode=meta.get('priority_class','live'))
        count+=1
    db.commit();return count


def run_once(now=None):
    if not settings.pipeline_enabled: return {'status':'disabled'}
    with engine.connect() as coordination:
        pg=engine.dialect.name=='postgresql'
        if pg and not coordination.scalar(text("SELECT pg_try_advisory_lock(hashtext('pipeline-restoration'))")):
            return {'status':'another_scheduler_running'}
        try:
            with SessionLocal() as db:
                recovered=recover(db);scheduled=schedule_sources(db,now or datetime.now(UTC));reconstructed=reconstruct(db) if not settings.pipeline_dispatch_scope else 0
                queued=dispatch(db,lambda identifier,stage,mode:execute.apply_async(args=(identifier,),
                    queue=QUEUES[stage],priority=8 if mode=='historical' else 0),scope=settings.pipeline_dispatch_scope)
                return {'status':'running','recovered':recovered,'scheduled':scheduled,'reconstructed':reconstructed,'queued':queued}
        finally:
            if pg: coordination.execute(text("SELECT pg_advisory_unlock(hashtext('pipeline-restoration'))"))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    while True:
        try: print(json.dumps(run_once()),flush=True)
        except Exception as exc: print(json.dumps({'status':'scheduler_error','code':type(exc).__name__}),flush=True)
        if args.once: return
        time.sleep(30)

if __name__=='__main__': main()
