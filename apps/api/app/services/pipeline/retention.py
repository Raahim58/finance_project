"""Capacity pressure defers work; it never relabels evidence as irrelevant."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import shutil
from sqlalchemy import func, select
from app.core.config import settings
from app.models.pipeline import IngestionStageRun, EnrichmentAttempt
from app.models.workstation import SourceArtifact

GIB=1024**3

def capacity(db, *, root=None):
    path=Path(root or settings.pipeline_data_root)
    if not path.exists(): return {'allow_live':False,'allow_history':False,'reason':'data_volume_unavailable'}
    free=shutil.disk_usage(path).free
    raw=0
    # Metadata byte counts measure logical bytes conservatively; the object
    # store may deduplicate physical copies. Missing older counts stay visible.
    missing=0
    for metadata in db.scalars(select(SourceArtifact.response_metadata_json).where(SourceArtifact.status!="purged")):
        try: data=json.loads(metadata or '{}');count=data.get('stored_bytes',data.get('bytes'))
        except (TypeError,ValueError): count=None
        if isinstance(count,int): raw+=count
        else: missing+=1
    budget=settings.pipeline_raw_budget_gib*GIB
    ratio=raw/max(1,budget)
    database_bytes=None
    if db.bind.dialect.name=='postgresql':
        database_bytes=db.scalar(select(func.pg_database_size(func.current_database())))
        ratio=max(ratio,database_bytes/max(1,settings.pipeline_database_budget_gib*GIB))
    enough=free>=settings.pipeline_min_free_gib*GIB
    return {'allow_live':enough and ratio<1,'allow_history':enough and ratio<.9,
        'alert':ratio>=.8,'raw_logical_bytes':raw,'database_bytes':database_bytes,'free_bytes':free,
        'unmeasured_legacy_artifacts':missing,'reason':'capacity_available' if enough and ratio<.9 else 'capacity_pressure'}

def daily_allowance(db,run, *, is_pdf=False,now=None):
    now=now or datetime.now(UTC);midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
    historical=run.mode=='historical'
    count=db.scalar(select(func.count()).select_from(IngestionStageRun).where(
        IngestionStageRun.stage==('report_fetch' if is_pdf else 'fetch'),
        IngestionStageRun.mode==run.mode,IngestionStageRun.heartbeat_at>=midnight,
        IngestionStageRun.status.in_(('running','completed')))) or 0
    limit=settings.pipeline_max_history_pdfs if is_pdf and historical else settings.pipeline_max_history_articles if historical else settings.pipeline_max_live_articles if not is_pdf else None
    used_bytes=0
    for metadata in db.scalars(select(SourceArtifact.response_metadata_json).where(SourceArtifact.retrieved_at>=midnight)):
        try: recorded=json.loads(metadata or '{}')
        except ValueError: continue
        if recorded.get('ingestion_mode')==run.mode: used_bytes+=int(recorded.get('bytes',0))
    byte_limit=(768 if historical else 256)*1024**2
    reserve=(25 if is_pdf else 5)*1024**2
    return (limit is None or count<=limit) and used_bytes+reserve<=byte_limit


def purge_attempt_payloads(db, *, now=None):
    """14-day encrypted model transport retention; statement/source lineage stays."""
    cutoff=(now or datetime.now(UTC))-timedelta(days=14);count=0
    for row in db.scalars(select(EnrichmentAttempt).where(EnrichmentAttempt.created_at<cutoff,
            EnrichmentAttempt.status.in_(('completed','failed','deferred')))):
        if row.request_encrypted or row.response_encrypted:
            row.request_encrypted=None;row.response_encrypted=None;count+=1
    db.flush();return count


def prune_unpromoted_raw(db,store, *, now=None,limit=50):
    """Expire uncited, terminal, unpromoted raw bytes after 30 days.

    Artifact metadata/hash remains. Every other FK consumer protects the blob;
    content-addressed objects shared by another capture are retained. Accepted
    document bytes are never removed by this maintenance path.
    """
    from sqlalchemy import or_
    from app.db.session import Base
    from app.models.pipeline import ArtifactPin
    from app.models.evidence import DiscoveryCandidate
    from app.models.document import Document
    cutoff=(now or datetime.now(UTC))-timedelta(days=30);purged=0
    rows=db.scalars(select(SourceArtifact).where(SourceArtifact.retrieved_at<cutoff,
        SourceArtifact.storage_path.is_not(None),SourceArtifact.status.in_(('captured','purge_pending')))
        .order_by(SourceArtifact.retrieved_at).limit(limit).with_for_update(skip_locked=True)).all()
    for artifact in rows:
        if db.scalar(select(ArtifactPin.artifact_id).where(ArtifactPin.artifact_id==artifact.id).limit(1)): continue
        candidates=list(db.scalars(select(DiscoveryCandidate).where(DiscoveryCandidate.artifact_id==artifact.id)))
        if any(c.status not in ('rejected','duplicate','expired') for c in candidates): continue
        protected=False
        for table in Base.metadata.tables.values():
            if table.name in ('discovery_candidates','source_artifacts'): continue
            for column in table.columns:
                if any(fk.target_fullname=='source_artifacts.id' for fk in column.foreign_keys):
                    if db.scalar(select(func.count()).select_from(table).where(column==artifact.id)):
                        protected=True;break
            if protected: break
        if protected: continue
        shared=db.scalar(select(SourceArtifact.id).where(SourceArtifact.storage_path==artifact.storage_path,SourceArtifact.id!=artifact.id).limit(1))
        path=artifact.storage_path
        # Terminal raw has no retrieval consumer. A rollback after object deletion
        # leaves a recoverable tombstone; replay must re-fetch from the source.
        artifact.status='purge_pending';db.flush()
        if not shared: store.delete(path)
        artifact.storage_path=None;artifact.status='purged'
        metadata=json.loads(artifact.response_metadata_json or '{}')
        artifact.response_metadata_json=json.dumps({**metadata,'purged_at':(now or datetime.now(UTC)).isoformat(),
            'retention_basis':'unpromoted_terminal_30d','stored_bytes':0})
        db.flush();purged+=1
    db.flush();return purged


def demote_vectors(db, *, limit=500):
    """Release old unpinned embeddings; keep all lexical text and citations."""
    from app.models.document import Document,DocumentChunk
    from app.models.pipeline import ArtifactPin
    cutoff=datetime.now(UTC).date()-timedelta(days=90)
    pinned=select(ArtifactPin.artifact_id)
    rows=db.scalars(select(DocumentChunk).join(Document,Document.id==DocumentChunk.document_id)
        .where(Document.document_type=='news',Document.published_date<cutoff,
            Document.visibility=='public',Document.owner_user_id.is_(None),Document.portfolio_id.is_(None),
            Document.artifact_id.not_in(pinned),DocumentChunk.embedding_vector.is_not(None))
        .order_by(Document.published_date).limit(limit).with_for_update(skip_locked=True)).all()
    for chunk in rows:
        chunk.embedding_vector=None;chunk.embedding_json='[]';chunk.embedding_status='lexical_only'
    db.flush();return len(rows)
