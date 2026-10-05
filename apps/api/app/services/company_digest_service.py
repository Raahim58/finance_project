"""Saved company digest reads and single-call refreshes on the existing research queue."""
import json
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.security import encrypt_secret
from app.domain.research_relevance import canonical, fingerprint
from app.models.research_intelligence import CompanyDigest, ResearchJob
from app.services.company_snapshot import dependency_hash
from app.services.research_job_service import generation_config

BRIEF_VERSION = 'company-brief.v1'


def digest_key(instrument, input_hash, config):
    return fingerprint({'company':instrument.id,'inputs':input_hash,'version':BRIEF_VERSION,**config})


def read_digest(db, user, instrument, *, active=False, retry=False):
    config = generation_config(db,user)
    input_hash = dependency_hash(db,instrument)
    statement = select(CompanyDigest).where(CompanyDigest.user_id == user.id,
        CompanyDigest.instrument_id == instrument.id, CompanyDigest.prompt_version == BRIEF_VERSION)
    if config:
        statement = statement.where(CompanyDigest.provider == config['provider'], CompanyDigest.model == config['model'])
    current = db.scalar(statement.where(CompanyDigest.input_hash == input_hash).order_by(CompanyDigest.generated_at.desc()).limit(1))
    previous = db.scalar(statement.where(CompanyDigest.brief_json.is_not(None)).order_by(CompanyDigest.generated_at.desc()).limit(1))
    chosen = current or previous
    key = digest_key(instrument,input_hash,config or {})
    root = db.scalar(select(ResearchJob).where(ResearchJob.user_id == user.id, ResearchJob.request_hash == key)
        .order_by(ResearchJob.created_at.desc(),ResearchJob.id).limit(1))
    ready = bool(current and current.brief_json)
    if active and config and not ready and (root is None or (retry and root.status in ('failed','uncertain','budget_exhausted'))):
        root = enqueue_refresh(db,user,instrument,input_hash,config,key,retry=retry)
    status = 'ready' if ready else root.status if root else 'provider_unavailable' if not config else 'not_generated'
    brief_row = current if ready else previous
    brief_sources = {}
    if brief_row:
        evidence = json.loads(brief_row.snapshot_json)
        brief_sources = {ref:[source] for ref,source in evidence['sources'].items()}
        for record in evidence['financials'] + evidence['news'] + evidence.get('corporate_actions',[]):
            brief_sources[record['id']] = [evidence['sources'][ref] for ref in record.get('evidence_refs',[]) if ref in evidence['sources']]
    return {'brief_sources':brief_sources,'status':status,'current':ready,'input_hash':input_hash,'job_id':root.id if root else None,
        'error_code':root.error_code if root else None,
        'snapshot':json.loads(current.snapshot_json) if current else json.loads(previous.snapshot_json) if previous else None,
        # A refreshed snapshot can be ready before its AI brief. Never pair a previous brief with new facts silently.
        'brief':json.loads(current.brief_json) if current and current.brief_json else json.loads(previous.brief_json) if previous else None,
        'brief_is_current':ready,'generated_at':previous.generated_at if previous and not ready else chosen.generated_at if chosen else None,
        'brief_input_hash':current.input_hash if ready else previous.input_hash if previous else None}


def enqueue_refresh(db,user,instrument,input_hash,config,key,*,retry=False):
    dedup = 'company-digest:' + key + (':' + uuid4().hex[:12] if retry else '')
    try:
        # Savepoint handles racing page opens without rolling back unrelated request work.
        with db.begin_nested():
            root = ResearchJob(user_id=user.id,job_type='batch',dedup_key=dedup,request_hash=key,
                max_calls=1,request_encrypted=encrypt_secret(canonical(config)),result_json='{}')
            db.add(root);db.flush()
            db.add(ResearchJob(user_id=user.id,parent_id=root.id,instrument_id=instrument.id,
                job_type='company_snapshot',dedup_key=dedup+':company',request_hash=input_hash,max_calls=1,
                request_encrypted=encrypt_secret(canonical(config)),result_json='{}'))
        db.commit()
    except IntegrityError:
        root = db.scalar(select(ResearchJob).where(ResearchJob.user_id == user.id,ResearchJob.dedup_key == dedup))
        if root is None: raise
    return root


def store_snapshot(db,user,instrument,payload,config):
    row = db.scalar(select(CompanyDigest).where(CompanyDigest.user_id == user.id,
        CompanyDigest.instrument_id == instrument.id,CompanyDigest.input_hash == payload['input_hash'],
        CompanyDigest.prompt_version == BRIEF_VERSION,CompanyDigest.provider == config['provider'],CompanyDigest.model == config['model']))
    if row is None:
        row = CompanyDigest(user_id=user.id,instrument_id=instrument.id,input_hash=payload['input_hash'],
            prompt_version=BRIEF_VERSION,provider=config['provider'],model=config['model'],snapshot_json=canonical(payload))
        db.add(row);db.flush()
    return row
