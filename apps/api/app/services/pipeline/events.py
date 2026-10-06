"""Conservative event clusters. No fuzzy merge silently changes periods or lifecycle."""
from datetime import UTC, datetime
from decimal import Decimal
import json
from sqlalchemy import select
from app.models.document import Document
from app.models.pipeline import EvidenceStatement, EventDocumentLink
from app.models.workstation import (NormalizedEvent, NormalizedEventSubject,NormalizedEventEvidence,Event,EventEntityLink,EventSource)
from app.services.pipeline.runs import fingerprint


def build(db,document_id):
    document=db.get(Document,document_id)
    if not document.published_date:
        return {'events':[], 'gap':'event_date_unverified'}
    occurred=datetime.combine(document.published_date,datetime.min.time(),tzinfo=UTC)
    from app.domain.event_intelligence import event_freshness
    freshness_score,freshness_status=event_freshness(occurred)
    ids=[]
    for stmt in db.scalars(select(EvidenceStatement).where(EvidenceStatement.document_id==document_id,
            EvidenceStatement.validation_status=='validated',EvidenceStatement.kind.in_(('reported_fact','management_claim','guidance')))):
        if not stmt.event_type: continue
        # Exact quote + subject + reported date is deliberately conservative.
        # Semantic merges require reviewed object/counterparty identity.
        key=fingerprint([stmt.subject_key,stmt.event_type,stmt.lifecycle,str(document.published_date),stmt.text])
        event=db.scalar(select(NormalizedEvent).where(NormalizedEvent.cluster_key==key))
        if event is None:
            event=NormalizedEvent(event_type=stmt.event_type,classification_status='classified',title=stmt.text[:255],
                occurred_at=occurred,cluster_key=key,materiality='medium' if stmt.subject_type=='instrument' and stmt.event_type in ('earnings','dividend','expansion','financing','regulatory','ownership','disruption') else 'low',confidence=Decimal('0.5'),
                freshness_score=freshness_score,freshness_status=freshness_status,detection_version='pipeline-v1',
                details_json=json.dumps({'lifecycle':stmt.lifecycle,'kind':stmt.kind,'date_basis':'publication_date',
                    'text':stmt.text,'not_a_financial_fact':True}))
            db.add(event);db.flush()
            db.add(NormalizedEventSubject(normalized_event_id=event.id,subject_type=stmt.subject_type,
                subject_key=stmt.subject_key,link_method='quote_link',confidence=Decimal('0.5'),is_direct=True))
        # Preserve existing consumers while allowing multiple events per doc:
        # each atomic statement receives its own raw compatibility record.
        raw_key='pipeline-statement:'+stmt.id
        raw=db.scalar(select(Event).where(Event.cluster_key==raw_key))
        if raw is None:
            raw=Event(event_type='announcement' if document.document_type!='news' else 'news',
                title=stmt.text[:255],occurred_at=occurred,cluster_key=raw_key,
                details_json=json.dumps({'statement_id':stmt.id,'kind':stmt.kind,'lifecycle':stmt.lifecycle,
                    'date_basis':'publication_date','materiality_basis':'corporate_event_category'}))
            db.add(raw);db.flush()
            if stmt.subject_type=='instrument':
                db.add(EventEntityLink(event_id=raw.id,entity_type='instrument',entity_key=stmt.subject_key,
                    link_method='stored_company_name',confidence=Decimal('0.5')))
            db.add(EventSource(event_id=raw.id,document_id=document.id,artifact_id=document.artifact_id,
                source_url=document.source_url or '',source_name=document.source_name,
                published_at=occurred,evidence_role='primary' if document.source_tier<=2 else 'reporting',selection_status='selected'))
            db.add(NormalizedEventEvidence(normalized_event_id=event.id,raw_event_id=raw.id,evidence_role=stmt.kind))
        pk=(event.id,document_id,stmt.id)
        if db.get(EventDocumentLink,pk) is None:
            db.add(EventDocumentLink(event_id=event.id,document_id=document_id,statement_id=stmt.id,role=stmt.kind))
        ids.append(event.id)
    db.flush();return {'events':list(dict.fromkeys(ids))}
