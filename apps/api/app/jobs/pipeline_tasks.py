"""Stage-run-ID-only workers. No automatic production starts or paid models."""
import asyncio
from datetime import UTC, datetime, timedelta
from dataclasses import asdict
import json
from sqlalchemy import select
from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.pipeline import IngestionStageRun
from app.models.evidence import DiscoveryCandidate
from app.models.workstation import EventSource, Instrument
from app.services.pipeline import runs

QUEUES={'briefing':'pipeline_heavy','discover':'pipeline_discovery','fetch':'pipeline_fetch','parse':'pipeline_parse',
    'index':'pipeline_heavy','sections':'pipeline_parse','link':'pipeline_parse','extract':'pipeline_enrich',
    'events':'pipeline_enrich','intelligence':'pipeline_intelligence','enrich':'pipeline_model',
    'secondary_tables':'pipeline_numeric','prices':'pipeline_numeric','reports':'pipeline_discovery','report_fetch':'pipeline_fetch',
    'report_index':'pipeline_heavy','report_extract':'pipeline_heavy','history_prices':'pipeline_numeric','maintenance':'pipeline_parse'}

class DeferredStage(Exception): pass


def successor(db,run,stage,payload):
    return [(stage,run.subject_key,payload)]


def perform(db,run):
    p=run.input;stage=run.stage
    if stage=='briefing':
        from app.services.pipeline.briefing import capture
        return capture(db),[]
    if stage=='discover':
        from app.ingestion.evidence_catalog import build_pass1_registry
        from app.services.evidence_operations import discover_stage
        source=build_pass1_registry().get(p['source_key'])
        if p.get('archive')=='mettis':
            from app.providers.evidence.mettis_archive import MettisArchiveSource
            source=MettisArchiveSource(cursor=p.get('cursor'),date_from=p.get('date_from'),date_to=p.get('date_to'))
        if p['source_key']=='tavily':
            from app.models.pipeline import ServiceCredential
            from app.core.security import decrypt_secret
            from app.providers.evidence.tavily import TavilyDiscoverySource
            key=db.scalar(select(ServiceCredential).where(ServiceCredential.purpose=='tavily_discovery',ServiceCredential.active.is_(True)))
            if not key: raise DeferredStage('tavily_credential_missing')
            source=TavilyDiscoverySource(api_key=decrypt_secret(key.secret_encrypted),query=p['query'],domains=p['domains'])
        result=discover_stage(db,source,limit=min(50,int(p.get("news_limit",50))),priority_class=run.mode if run.mode!='replay' else 'live',
            cursor_override=p.get('cursor') if p.get('archive') or p.get('source_key')=='psx_announcements' else None)
        children=[('fetch','candidate:'+c,{'candidate_id':c,'revision':json.loads(db.get(DiscoveryCandidate,c).metadata_json or '{}').get('pipeline_revision',0)}) for c in result.candidate_ids]
        if p.get('archive')=='mettis' and not (result.next_cursor or {}).get('complete') and not p.get('canary_batch'):
            page=int(p.get('page',0))
            if page<99 and (run.mode=='historical' or result.new or (result.next_cursor or {}).get('initial_listing')):
                cursor=dict(result.next_cursor);cursor.pop('initial_listing',None)
                children.append(('discover',run.subject_key,dict(p,cursor=cursor,page=page+1)))
        if p.get('source_key')=='psx_announcements' and not p.get('canary_batch') and result.discovered==50 and int(p.get('page',0))<19:
            cursor={**p.get('cursor',{}),**(result.next_cursor or {})}
            children.append(('discover',run.subject_key,dict(p,cursor=cursor,page=int(p.get('page',0))+1)))
        return asdict(result),children
    if stage in ('fetch','parse','index'):
        from app.jobs.evidence_tasks import _source_for_candidate
        from app.services.evidence_operations import fetch_stage,parse_stage,index_stage
        source,row=_source_for_candidate(db,p['candidate_id'])
        if p.get('revision',0)!=json.loads(row.metadata_json or '{}').get('pipeline_revision',0):
            return {'status':'superseded_stage_input'},[]
        if stage=='fetch':
            from app.services.pipeline.retention import capacity,daily_allowance
            pressure=capacity(db)
            if not pressure['allow_history' if run.mode=='historical' else 'allow_live'] or not daily_allowance(db,run): raise DeferredStage('capacity_deferred')
            result=fetch_stage(db,source,row.id)
            if result.outcome.endswith('deferred') or result.outcome.endswith('budget_reached'):
                raise DeferredStage(result.outcome)
            meta=json.loads(row.metadata_json or '{}').get('_pipeline',{})
            children=[('parse',run.subject_key,p)] if result.outcome=='raw_ready' or meta.get('stage')=='raw_ready' else []
        elif stage=='parse':
            meta=json.loads(row.metadata_json or '{}').get('_pipeline',{})
            # Restore disposable spool bytes from immutable raw capture.
            from app.services.evidence_operations import EvidenceSpool
            from app.ingestion.artifact_store import get_artifact_store
            from app.models.workstation import SourceArtifact
            spool=EvidenceSpool()
            try: spool.read_raw(row.id)
            except FileNotFoundError:
                artifact=db.get(SourceArtifact,row.artifact_id)
                if not artifact or not artifact.storage_path: raise ValueError('raw_artifact_missing')
                content=get_artifact_store(settings).get(artifact.storage_path)
                if 'gzip' in (artifact.content_type or ''):
                    import gzip
                    content=gzip.decompress(content)
                spool.write_raw(row.id,content)
            result=parse_stage(db,source,row.id,pdf='pdf' in str(meta.get('content_type','')).lower())
            children=[('index',run.subject_key,p)] if result.outcome=='index_ready' or row.status=='clustered' else []
        else:
            result=index_stage(db,row.id)
            if result.outcome.endswith('deferred'): raise DeferredStage(result.outcome)
            event_source=db.scalar(select(EventSource).where(EventSource.candidate_id==row.id))
            children=[('sections','document:'+event_source.document_id,{'document_id':event_source.document_id})] if event_source and event_source.document_id else []
        return asdict(result),children
    if stage=='report_index':
        from app.services.research_evidence_service import prepare_report
        result=prepare_report(db,p['document_id'])
        return result,successor(db,run,'sections',p)
    if stage=='sections':
        from app.services.pipeline.parsing import sections
        result=sections(db,p['document_id'])
        return {'sections':[r.id for r in result]},successor(db,run,'link',p)
    if stage=='link':
        from app.services.pipeline.linking import link
        result=link(db,p['document_id'])
        return {'instruments':result},successor(db,run,'extract',p)
    if stage=='extract':
        from app.services.pipeline.statements import extract
        result=extract(db,p['document_id'])
        return {'statements':result},successor(db,run,'events',p)
    if stage=='events':
        from app.services.pipeline.events import build
        from app.models.pipeline import DocumentEntityLink
        result=build(db,p['document_id'])
        from app.models.document import Document
        document=db.get(Document,p['document_id'])
        issuer=db.scalar(select(Instrument.id).where(Instrument.symbol==document.symbol)) if document and document.symbol and document.document_type!='news' else None
        ids=[issuer] if issuer else db.scalars(select(DocumentEntityLink.instrument_id).where(DocumentEntityLink.document_id==p['document_id'])).all()
        return result,[('intelligence','instrument:'+i,{'instrument_id':i,'document_id':p['document_id'],'version':run.input_hash}) for i in ids]
    if stage=='intelligence':
        from app.services.pipeline.intelligence import refresh
        return {'sections':refresh(db,p['instrument_id'])},[]
    if stage=='enrich':
        if not settings.pipeline_enrichment_enabled: return {'status':'blocked','gap':'enrichment_disabled'},[]
        from app.services.pipeline.enrichment import enrich
        return asyncio.run(enrich(db,run)),[]
    if stage=='secondary_tables':
        from app.services.pipeline.secondary import capture
        return capture(db,p['symbol']),[]
    if stage=='prices':
        from app.services.pipeline.prices import refresh
        result=refresh(db,symbols=p.get("symbols"))
        if result.get("source_market_state")=="pre-open": raise DeferredStage("market_pre_open")
        return result,[]
    if stage=='reports':
        from app.providers.fundamentals.psx_financials import PsxFinancialsProvider
        provider=PsxFinancialsProvider()
        items=sorted(provider.fetch_company_catalog(p['symbol']),key=lambda item:item.posting_date,reverse=True)
        if p.get('report_limit'):
            items=items[:int(p['report_limit'])]
        elif run.mode!='historical':
            from app.models.document import Document
            known=set(db.scalars(select(Document.source_url).where(Document.symbol==p['symbol'],Document.status!='superseded')))
            recent=datetime.now(UTC).date()-timedelta(days=14)
            items=[item for item in items[:20] if item.report_url not in known or item.posting_date>=recent]
        children=[]
        for item in items:
            payload=asdict(item);payload['posting_date']=item.posting_date.isoformat()
            children.append(('report_fetch','report:'+item.report_id,{'report':payload,'capture_bucket':p.get('bucket') or p.get('as_of')}))
        return {'catalog_items':len(items),'scope':'all_accessible_catalog' if run.mode=='historical' else 'recent_catalog'},children
    if stage in ('report_fetch','report_extract','history_prices'):
        from app.jobs import phase2_tasks
        from app.services.pipeline.retention import capacity,daily_allowance
        if stage=='report_fetch':
            pressure=capacity(db)
            if not pressure['allow_history' if run.mode=='historical' else 'allow_live'] or not daily_allowance(db,run,is_pdf=True): raise DeferredStage('capacity_deferred')
            # Existing download task persists report + numeric work. It is
            # idempotent; the DB outbox below also reconstructs its extraction.
            result=phase2_tasks.financial_download_pdf(p['report'])
            from app.models.workstation import SourceArtifact
            from app.models.document import Document
            document=db.get(Document,result.get('document_id')) if result.get('document_id') else None
            if document and document.artifact_id:
                artifact=db.get(SourceArtifact,document.artifact_id)
                artifact.response_metadata_json=json.dumps({**json.loads(artifact.response_metadata_json or '{}'),'ingestion_mode':run.mode})
            return result,successor(db,run,'report_extract',dict(p,document_id=result.get('document_id')))
        if stage=='report_extract':
            item=phase2_tasks._item(p['report'])
            from app.models.document import Document
            doc=db.get(Document,p['document_id']) if p.get('document_id') else db.scalar(select(Document).where(Document.source_url==item.report_url,Document.status!='superseded').order_by(Document.created_at.desc()).limit(1))
            if not doc: raise ValueError('report_document_missing')
            result=phase2_tasks.financial_extract(doc.id)
            return result,[('report_index','document:'+doc.id,{'document_id':doc.id})]
        return phase2_tasks.dps_history(p['symbol'],p['year'],p['month']),[]
    if stage=='maintenance':
        from app.services.pipeline.retention import capacity,purge_attempt_payloads,prune_unpromoted_raw,demote_vectors
        from app.ingestion.artifact_store import get_artifact_store
        result={"encrypted_payloads_purged":purge_attempt_payloads(db),
            "unpromoted_raw_purged":prune_unpromoted_raw(db,get_artifact_store(settings)),"vectors_demoted":demote_vectors(db)}
        return {**result,**capacity(db)},[]
    raise ValueError('unknown_pipeline_stage')


@celery_app.task(name='pipeline.execute',soft_time_limit=270,time_limit=300)
def execute(run_id):
    if not settings.pipeline_enabled: return {'status':'disabled'}
    with SessionLocal() as db:
        token=runs.claim(db,run_id)
        if not token: return {'status':'already_claimed_or_terminal'}
        try:
            run=db.get(IngestionStageRun,run_id)
            # New document stages lock their subject before writing. Legacy
            # adapters keep their own commit/replay rules until migrated.
            if run.stage in ('sections','link','extract','events'):
                from app.models.document import Document
                db.scalar(select(Document).where(Document.id==run.input['document_id']).with_for_update())
            elif run.stage=='intelligence':
                db.scalar(select(Instrument).where(Instrument.id==run.input['instrument_id']).with_for_update())
            output,children=perform(db,run)
            runs.finish(db,run_id,token,output,children=children)
            return output
        except DeferredStage as exc:
            db.rollback();run=db.get(IngestionStageRun,run_id)
            if run.lease_token==token:
                run.status='retry_wait';run.next_attempt_at=datetime.now(UTC)+timedelta(seconds=60 if str(exc)=='market_pre_open' else 3600)
                run.attempt_count=max(0,run.attempt_count-1);run.error_code=str(exc)
                run.lease_token=None;run.lease_until=None;db.commit()
            return {'status':'deferred'}
        except Exception as exc:
            runs.fail(db,run_id,token,type(exc).__name__,permanent=isinstance(exc,ValueError))
            raise
