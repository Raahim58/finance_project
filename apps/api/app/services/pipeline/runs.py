"""DB outbox, leases and fencing. Queue messages contain only stage-run IDs."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import uuid4
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from app.models.pipeline import IngestionStageRun

VERSION = 'pipeline-v1'
LEASE_SECONDS = 360
MAX_ATTEMPTS = 5

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
    for stage, subject, payload in children:
        if row.input.get("canary_batch"):
            payload={**payload,"canary_batch":row.input["canary_batch"]}
            if not subject.startswith("canary:"): subject="canary:"+row.input["canary_batch"]+":"+subject
        enqueue(db, stage, subject, payload, mode=row.mode)
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
    for mode, quota in (('live',max(1,limit*4//5)),('historical',max(1,limit//5)),('replay',limit)):
        slots=min(quota,limit-len(chosen))
        if slots<=0: break
        rows=db.scalars(select(IngestionStageRun).where(*conditions,IngestionStageRun.mode==mode)
            .order_by(IngestionStageRun.created_at,IngestionStageRun.id).limit(slots)
            .with_for_update(skip_locked=True)).all()
        for row in rows: row.dispatch_until=now+timedelta(seconds=60)
        chosen.extend((r.id,r.stage,r.mode) for r in rows)
    db.commit()
    published=0
    for identifier,stage,mode in chosen:
        try:
            publish(identifier,stage,mode); published+=1
        except Exception:
            # Keep reservation until retry; don't log credentials or raw payloads.
            pass
    return published
