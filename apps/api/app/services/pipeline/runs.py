"""DB outbox, leases and fencing. Queue messages contain only stage-run IDs."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import uuid4
from sqlalchemy import exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from app.models.pipeline import IngestionStageRun

VERSION = 'pipeline-v1'
LEASE_SECONDS = 360
MAX_ATTEMPTS = 5
REPORT_STAGES = ('reports','report_fetch','report_extract','report_index')
REPORT_ACQUISITION_STAGES = ('reports', 'report_fetch')
PROCESSING_PRIORITY = ('intelligence', 'events', 'classify', 'extract', 'link', 'sections',
                       'report_index', 'report_extract', 'index', 'parse')
URGENT_STAGES = ('briefing','discover','fetch','parse','index','sections','link','extract','classify','events','intelligence','prices','market_daily')

def report_work_condition():
    from app.models.document import Document
    return or_(IngestionStageRun.stage.in_(REPORT_STAGES), exists(select(Document.id).where(
        Document.id==IngestionStageRun.input['document_id'].as_string(),
        Document.document_type.in_(('annual_report','quarterly_report','interim_report')))))

def urgent_work_pending(db, *, now=None,scope=''):
    now=now or datetime.now(UTC)
    conditions=(~report_work_condition(),IngestionStageRun.stage.in_(URGENT_STAGES),
        IngestionStageRun.status.in_(('queued','retry_wait','running')),
        or_(IngestionStageRun.next_attempt_at.is_(None),IngestionStageRun.next_attempt_at<=now))
    if scope:conditions=(*conditions,IngestionStageRun.subject_key.like(scope+':%'))
    return bool(db.scalar(select(IngestionStageRun.id).where(*conditions).limit(1)))

def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value

def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

def enqueue(db, stage, subject_key, payload, *, mode='live', version=VERSION):
    if mode not in ('live','historical','replay'):
        raise ValueError('Invalid ingestion mode')
    if len(json.dumps(payload)) > 16384:
        raise ValueError('Stage inputs must contain bounded IDs/cursors, not document bodies')
    digest = fingerprint(payload)
    query = select(IngestionStageRun).where(IngestionStageRun.stage==stage,
        IngestionStageRun.subject_key==subject_key, IngestionStageRun.input_hash==digest,
        IngestionStageRun.code_version==version)
    existing = db.scalar(query)
    if existing: return existing
    try:
        with db.begin_nested():
            row = IngestionStageRun(stage=stage, subject_key=subject_key, input_hash=digest,
                code_version=version, mode=mode, input=payload)
            db.add(row); db.flush()
        return row
    except IntegrityError:
        row = db.scalar(query)
        if row is None: raise
        return row

def claim(db, run_id, *, now=None):
    now = now or datetime.now(UTC)
    token = str(uuid4())
    result = db.execute(update(IngestionStageRun).execution_options(synchronize_session=False).where(IngestionStageRun.id==run_id,
        IngestionStageRun.status.in_(('queued','retry_wait')),
        or_(IngestionStageRun.next_attempt_at.is_(None), IngestionStageRun.next_attempt_at<=now))
        .values(status='running', lease_token=token, lease_until=now+timedelta(seconds=LEASE_SECONDS),
            heartbeat_at=now, attempt_count=IngestionStageRun.attempt_count+1, dispatch_until=None))
    db.commit()
    return token if result.rowcount else None

def finish(db, run_id, token, output, *, children=()):
    now = datetime.now(UTC)
    row = db.scalar(select(IngestionStageRun).where(IngestionStageRun.id==run_id).with_for_update())
    if not row or row.status!='running' or row.lease_token!=token or utc(row.lease_until)<=now:
        raise RuntimeError('stale_stage_lease')
    for child in children:
        stage,subject,payload=child[:3]
        child_mode=child[3] if len(child)>3 else row.mode
        if row.input.get("canary_batch"):
            payload={**payload,"canary_batch":row.input["canary_batch"]}
            if not subject.startswith("canary:"): subject="canary:"+row.input["canary_batch"]+":"+subject
        enqueue(db, stage, subject, payload, mode=child_mode)
    row.output=output; row.status='completed'; row.finished_at=now
    row.lease_token=None; row.lease_until=None; row.error_code=None
    # Stage writes, completion and successor outbox rows commit together.
    db.commit()

def fail(db, run_id, token, error_code, *, permanent=False):
    db.rollback()
    row = db.scalar(select(IngestionStageRun).where(IngestionStageRun.id==run_id).with_for_update())
    if not row or row.lease_token!=token or row.status!='running': return
    row.status='dead_letter' if permanent or row.attempt_count>=MAX_ATTEMPTS else 'retry_wait'
    row.next_attempt_at=datetime.now(UTC)+timedelta(seconds=min(900,30*2**(row.attempt_count-1)))
    row.error_code=error_code[:100]  # Never persist exception bodies containing keys/payloads.
    row.lease_token=None; row.lease_until=None
    db.commit()

def recover(db, *, now=None):
    now=now or datetime.now(UTC)
    rows=db.scalars(select(IngestionStageRun).where(IngestionStageRun.status=='running',
        IngestionStageRun.lease_until<=now).with_for_update(skip_locked=True)).all()
    for row in rows:
        row.status='dead_letter' if row.attempt_count>=MAX_ATTEMPTS else 'retry_wait'
        row.next_attempt_at=now; row.lease_token=None; row.lease_until=None
        row.error_code='worker_lease_expired'
    db.commit()
    return len(rows)

def dispatch(db, publish, *, limit=20, now=None,scope=""):
    now=now or datetime.now(UTC)
    # Reserve before publish. A failed publish or crash is recoverable after 60s.
    conditions=(IngestionStageRun.status.in_(('queued','retry_wait')),
        or_(IngestionStageRun.next_attempt_at.is_(None),IngestionStageRun.next_attempt_at<=now),
        or_(IngestionStageRun.dispatch_until.is_(None),IngestionStageRun.dispatch_until<=now))
    if scope:
        conditions=(*conditions,IngestionStageRun.subject_key.like(scope+":%"))
    chosen=[]
    report_work=report_work_condition()
    # News/commentary and current observations finish before report work, across
    # live/history/replay modes. Deferred future retries do not block the queue.
    urgent_pending=urgent_work_pending(db,now=now,scope=scope)
    from sqlalchemy import case
    processing = report_work & ~IngestionStageRun.stage.in_(REPORT_ACQUISITION_STAGES)
    # Already downloaded reports must keep moving while fresh news is arriving.
    # Reserve a small processing share; news retains priority over new downloads.
    families = ((processing, max(1, limit//5)), (~report_work, limit)) if urgent_pending else (
        (processing, max(1, limit//5)), (~report_work, limit), (report_work, limit))
    priority = case({stage: rank for rank, stage in enumerate(PROCESSING_PRIORITY)},
                    value=IngestionStageRun.stage, else_=len(PROCESSING_PRIORITY))
    for family, family_cap in families:
        family_selected = 0
        for mode, quota in (('live',max(1,limit*4//5)),('historical',max(1,limit//5)),('replay',limit)):
            slots=min(quota,limit-len(chosen),family_cap-family_selected)
            if slots<=0: break
            rows=db.scalars(select(IngestionStageRun).where(*conditions,family,IngestionStageRun.mode==mode)
                .order_by(priority, IngestionStageRun.created_at,IngestionStageRun.id).limit(slots)
                .with_for_update(skip_locked=True)).all()
            for row in rows: row.dispatch_until=now+timedelta(seconds=60)
            chosen.extend((r.id,r.stage,r.mode) for r in rows)
            family_selected += len(rows)
    db.commit()
    published=0
    for identifier,stage,mode in chosen:
        try:
            publish(identifier,stage,mode); published+=1
        except Exception:
            # Keep reservation until retry; don't log credentials or raw payloads.
            pass
    return published
