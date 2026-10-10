"""Semantic event clusters with hard merge blockers; one answering record per event.

Candidates come from SQL (shared entity, same type, compatible period and date
window). Evidence text is then compared with the configured embeddings, so
different wording can join the same event. Similarity alone never merges:
conflicting amounts, opposite directions, different counterparties or
different reporting periods block it. Lifecycle changes are recorded as
updates with both states and their sources preserved.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from sqlalchemy import select
from app.models.document import Document
from app.models.pipeline import EventClusterFeature, EvidenceStatement, EventDocumentLink, StatementEvidence, DocumentSection
from app.models.workstation import (NormalizedEvent, NormalizedEventSubject, NormalizedEventEvidence, Event, EventEntityLink, EventSource)
from app.services.pipeline.runs import fingerprint

VERSION = 'pipeline-v2'
EVENT_KINDS = ('reported_fact', 'secondary_report', 'management_claim', 'guidance')
MATERIAL_TYPES = ('earnings', 'dividend', 'expansion', 'financing', 'regulatory', 'ownership', 'disruption', 'corporate_action', 'guidance')
OFFICIAL_TYPES = ('annual_report', 'quarterly_report', 'interim_report', 'announcement')
# Measured on MiniLM with entity names neutralised: same-event paraphrases
# scored 0.66-0.78, distinct same-company events 0.20-0.44.
MERGE_SIMILARITY = 0.65
DATE_WINDOW = timedelta(days=10)
PERIOD_WINDOW = timedelta(days=60)
LIFECYCLE_RANK = {'unknown': 0, 'updated': 1, 'proposed': 2, 'announced': 3, 'approved': 4, 'effective': 5, 'completed': 6, 'cancelled': 7}


def neutral_text(db, text, entities):
    """'LUCK' and 'Lucky Cement Limited' must not decide similarity; the SQL entity join already did."""
    import re
    from app.models.workstation import Instrument, InstrumentAlias
    names = []
    for inst in db.scalars(select(Instrument).where(Instrument.symbol.in_([e for e in entities if e != 'market']))):
        names += [inst.symbol, inst.name, *db.scalars(select(InstrumentAlias.alias).where(InstrumentAlias.instrument_id==inst.id))]
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(r'(?<!\w)'+re.escape(name)+r'(?!\w)', 'the company', text, flags=re.I)
    return text


def cosine(left, right):
    if not left or not right or len(left) != len(right): return 0.0
    from app.domain.retrieval import cosine_similarity
    return cosine_similarity(left, right)


def amount_conflict(left, right):
    """Same unit with no shared value is a different event, not a rewording."""
    from app.services.pipeline.classification import normalize_unit, numeric
    def by_unit(claims):
        values = {}
        for claim in claims:
            value = numeric(claim.get('value'))
            if value is not None: values.setdefault(normalize_unit(claim.get('unit')), set()).add(value)
        return values
    a, b = by_unit(left), by_unit(right)
    return any(a[unit].isdisjoint(b[unit]) for unit in set(a) & set(b))


def merge_blockers(features, candidate):
    blockers = []
    if features['reporting_period'] and candidate.reporting_period and features['reporting_period'] != candidate.reporting_period:
        blockers.append('reporting_period')
    if features['counterparties'] and candidate.counterparties and not (
            {c.lower() for c in features['counterparties']} & {c.lower() for c in candidate.counterparties}):
        blockers.append('counterparty')
    if {features['direction'], candidate.direction} == {'increase', 'decrease'}: blockers.append('direction')
    if amount_conflict(features['amounts'], candidate.amounts): blockers.append('amount')
    return blockers


def statement_features(statement, document):
    """Classifier statements carry their features; legacy statements get unknowns."""
    typed = statement.typed_value or {}
    published = datetime.combine(document.published_date, datetime.min.time(), tzinfo=UTC) if document.published_date else None
    event_date = datetime.fromisoformat(typed['event_date']).replace(tzinfo=UTC) if typed.get('event_date') else None
    spans = typed.get('evidence') or [{'section_id': None, 'quote': statement.text}]
    return {'group': (typed.get('classification_id'), typed.get('event_index')) if 'event_index' in typed else ('statement', statement.id),
        'entities': typed.get('entities') or [statement.subject_key], 'event_type': statement.event_type,
        'occurred': event_date or published, 'date_basis': 'event_date' if event_date else 'publication_date',
        'reporting_period': typed.get('reporting_period'), 'counterparties': typed.get('counterparties') or [],
        'amounts': [dict(a, document_id=document.id) for a in typed.get('amounts') or []],
        'direction': typed.get('direction') or 'unknown', 'text': ' '.join(s['quote'] for s in spans),
        'method': typed.get('method') or statement.method}


def candidates(db, features):
    window = PERIOD_WINDOW if features['reporting_period'] else DATE_WINDOW
    query = (select(NormalizedEvent, EventClusterFeature)
        .join(EventClusterFeature, EventClusterFeature.event_id==NormalizedEvent.id)
        .join(NormalizedEventSubject, NormalizedEventSubject.normalized_event_id==NormalizedEvent.id)
        .where(NormalizedEvent.detection_version==VERSION, NormalizedEvent.classification_status=='classified',
            NormalizedEvent.event_type==features['event_type'],
            NormalizedEventSubject.subject_key.in_(features['entities']),
            NormalizedEvent.occurred_at>=features['occurred']-window, NormalizedEvent.occurred_at<=features['occurred']+window)
        .distinct().order_by(NormalizedEvent.occurred_at.desc()).limit(50))
    if features['reporting_period']:
        query = query.where((EventClusterFeature.reporting_period.is_(None)) | (EventClusterFeature.reporting_period==features['reporting_period']))
    return list(db.execute(query))


def find_match(db, features, document_id, embedding):
    best, best_score = None, MERGE_SIMILARITY
    for event, feature in candidates(db, features):
        # The classifier already separated events within one article.
        if db.scalar(select(EventDocumentLink.event_id).where(EventDocumentLink.event_id==event.id,
                EventDocumentLink.document_id==document_id).limit(1)): continue
        score = cosine(embedding, feature.embedding)
        if score < MERGE_SIMILARITY: continue
        if merge_blockers(features, feature): continue
        if score >= best_score: best, best_score = (event, feature), score
    return best


def build(db, document_id):
    from app.services.rag_service import active_embedding_model, embed_texts
    document = db.get(Document, document_id)
    statements = list(db.scalars(select(EvidenceStatement).where(EvidenceStatement.document_id==document_id,
        EvidenceStatement.validation_status=='validated', EvidenceStatement.kind.in_(EVENT_KINDS),
        EvidenceStatement.event_type.is_not(None)).order_by(EvidenceStatement.id)))
    groups = {}
    for statement in statements:
        features = statement_features(statement, document)
        if features['occurred'] is None: continue
        groups.setdefault(features['group'], (features, []))[1].append(statement)
    if statements and not groups: return {'events': [], 'gap': 'event_date_unverified'}
    pending = [(f, rows) for f, rows in groups.values()
        if not all(db.scalar(select(EventDocumentLink.event_id).where(EventDocumentLink.statement_id==s.id).limit(1)) for s in rows)]
    vectors = embed_texts([neutral_text(db, f['text'], f['entities']) for f, _ in pending])
    ids = []
    for (features, rows), embedding in zip(pending, vectors):
        match = find_match(db, features, document_id, embedding)
        if match:
            event, feature = match
            feature.entities = sorted(set(feature.entities) | set(features['entities']))
            feature.reporting_period = feature.reporting_period or features['reporting_period']
            feature.counterparties = sorted(set(feature.counterparties) | set(features['counterparties']))
            feature.amounts = [*feature.amounts, *features['amounts']]
            if feature.direction == 'unknown': feature.direction = features['direction']
        else:
            event = NormalizedEvent(event_type=features['event_type'], classification_status='classified', title=rows[0].text[:255],
                occurred_at=features['occurred'], cluster_key=fingerprint([VERSION, rows[0].id]), materiality='low',
                confidence=Decimal('0.5'), freshness_score=Decimal('0'), freshness_status='stale',
                detection_version=VERSION, details_json='{}')
            db.add(event);db.flush()
            db.add(EventClusterFeature(event_id=event.id, entities=sorted(features['entities']),
                reporting_period=features['reporting_period'], counterparties=sorted(features['counterparties']),
                amounts=features['amounts'], direction=features['direction'], embedding_model=active_embedding_model(), embedding=embedding))
        for statement in rows: attach(db, event, statement, document)
        refresh_record(db, event)
        ids.append(event.id)
    for _, rows in groups.values():
        for statement in rows:
            ids.extend(db.scalars(select(EventDocumentLink.event_id).where(EventDocumentLink.statement_id==statement.id)))
    db.flush()
    return {'events': list(dict.fromkeys(ids))}


def attach(db, event, statement, document):
    """Member link plus the raw compatibility record existing readers expect."""
    occurred = datetime.combine(document.published_date, datetime.min.time(), tzinfo=UTC) if document.published_date else event.occurred_at
    raw_key = 'pipeline-statement:'+statement.id
    raw = db.scalar(select(Event).where(Event.cluster_key==raw_key))
    if raw is None:
        raw = Event(event_type='announcement' if document.document_type != 'news' else 'news',
            title=statement.text[:255], occurred_at=occurred, cluster_key=raw_key,
            details_json=json.dumps({'statement_id': statement.id, 'kind': statement.kind, 'lifecycle': statement.lifecycle,
                'date_basis': 'publication_date', 'materiality_basis': 'corporate_event_category'}))
        db.add(raw);db.flush()
        if statement.subject_type == 'instrument':
            db.add(EventEntityLink(event_id=raw.id, entity_type='instrument', entity_key=statement.subject_key,
                link_method='classified_entity', confidence=Decimal('0.5')))
        db.add(EventSource(event_id=raw.id, document_id=document.id, artifact_id=document.artifact_id,
            source_url=document.source_url or '', source_name=document.source_name, published_at=occurred,
            evidence_role='primary' if document.source_tier <= 2 else 'reporting', selection_status='selected'))
        db.add(NormalizedEventEvidence(normalized_event_id=event.id, raw_event_id=raw.id, evidence_role=statement.kind))
    if db.get(EventDocumentLink, (event.id, document.id, statement.id)) is None:
        db.add(EventDocumentLink(event_id=event.id, document_id=document.id, statement_id=statement.id, role=statement.kind))
    if db.scalar(select(NormalizedEventSubject).where(NormalizedEventSubject.normalized_event_id==event.id,
            NormalizedEventSubject.subject_type==statement.subject_type, NormalizedEventSubject.subject_key==statement.subject_key)) is None:
        db.add(NormalizedEventSubject(normalized_event_id=event.id, subject_type=statement.subject_type,
            subject_key=statement.subject_key, link_method='classified_entity', confidence=Decimal('0.5'), is_direct=True))
    db.flush()


def public(document):
    return bool(document and document.visibility == 'public' and document.owner_user_id is None
        and document.portfolio_id is None and document.status not in ('revoked', 'superseded', 'failed'))


def refresh_record(db, event):
    """Recompute the answering record from every current member statement."""
    from app.domain.event_intelligence import event_freshness
    members = []
    for link, statement, document in db.execute(select(EventDocumentLink, EvidenceStatement, Document)
            .join(EvidenceStatement, EvidenceStatement.id==EventDocumentLink.statement_id)
            .join(Document, Document.id==EventDocumentLink.document_id)
            .where(EventDocumentLink.event_id==event.id)):
        if statement.validation_status == 'validated' and public(document):
            members.append((statement, document, statement_features(statement, document)))
    if not members:
        event.classification_status = 'superseded';return event
    members.sort(key=lambda m: (m[1].source_tier, m[2]['occurred'], m[0].id))
    primary_statement, primary_document, _ = members[0]
    dated = [m[2]['occurred'] for m in members if m[2]['date_basis'] == 'event_date']
    occurred = min(dated) if dated else min(m[2]['occurred'] for m in members)
    # Lifecycle history keeps every observed state with its source; the
    # current state is the latest observation, and unknown never overrides.
    history = {}
    for statement, document, _ in members:
        key = (statement.lifecycle, document.id)
        entry = history.setdefault(key, {'lifecycle': statement.lifecycle, 'document_id': document.id,
            'source_name': document.source_name, 'observed_on': str(document.published_date) if document.published_date else None,
            'statement_ids': []})
        entry['statement_ids'] = sorted({*entry['statement_ids'], statement.id})
    timeline = sorted(history.values(), key=lambda h: (h['observed_on'] or '', LIFECYCLE_RANK.get(h['lifecycle'], 0)))
    known = [h for h in timeline if h['lifecycle'] != 'unknown']
    current = known[-1]['lifecycle'] if known else 'unknown'
    spans, used_documents = [], set()
    for statement, document, features in members:
        if document.id in used_documents or len(spans) >= 3: continue
        used_documents.add(document.id)
        typed = statement.typed_value or {}
        span = (typed.get('evidence') or [{'section_id': None, 'quote': statement.text}])[0]
        evidence = db.scalar(select(StatementEvidence).where(StatementEvidence.statement_id==statement.id).limit(1))
        section = db.get(DocumentSection, evidence.section_id) if evidence else None
        raw_id = db.scalar(select(Event.id).where(Event.cluster_key=='pipeline-statement:'+statement.id))
        spans.append({'quote': span['quote'][:600], 'statement_id': statement.id, 'raw_event_id': raw_id, 'document_id': document.id,
            'section_id': section.id if section else None, 'page_number': section.page_number if section else None,
            'start_offset': evidence.start_offset if evidence else None, 'end_offset': evidence.end_offset if evidence else None,
            'title': document.title, 'source_name': document.source_name, 'source_url': document.source_url,
            'published_date': str(document.published_date) if document.published_date else None, 'source_tier': document.source_tier})
    sentiments = [s.sentiment for s, _, _ in members if (s.sentiment or {}).get('quote')]
    documents = {d.id: d for _, d, _ in members}
    feature = db.get(EventClusterFeature, event.id)
    official = any(d.document_type in OFFICIAL_TYPES and d.source_tier <= 2 for d in documents.values())
    instrument = any(s.subject_type == 'instrument' for s, _, _ in members)
    if instrument and event.event_type in MATERIAL_TYPES: materiality = 'high' if official else 'medium'
    elif not instrument and event.event_type in ('macro', 'geopolitics'): materiality = 'medium'
    else: materiality = 'low'
    base = max(Decimal('0.65') if m[2]['method'] == 'model' else Decimal('0.45') for m in members)
    confidence = min(Decimal('0.95'), base + Decimal('0.1')*official + Decimal('0.08')*(len(documents)-1))
    # A news statement is a mid-article sentence; the headline is the readable title.
    headline = (primary_document.title or '').strip() if primary_document.document_type == 'news' else ''
    event.title = (headline or primary_statement.text)[:255]
    event.occurred_at = occurred
    event.materiality = materiality
    event.confidence = confidence.quantize(Decimal('0.000001'))
    event.freshness_score, event.freshness_status = event_freshness(occurred)
    event.classification_status = 'classified'
    event.details_json = json.dumps({'lifecycle': current, 'lifecycle_history': timeline,
        'kind': primary_statement.kind, 'date_basis': 'event_date' if dated else 'publication_date',
        'reporting_period': feature.reporting_period if feature else None,
        'direction': feature.direction if feature else 'unknown',
        'counterparties': feature.counterparties if feature else [],
        'amount_claims': [dict(a, basis='attributed_claim') for a in (feature.amounts if feature else [])][:10],
        'sectors': sorted({s for st, _, _ in members for s in (st.typed_value or {}).get('sectors', [])}),
        'topics': sorted({t for st, _, _ in members for t in st.topics or []}),
        'sentiment': sentiments[0] if sentiments else {'direction': 'unknown', 'reason': 'not_assessed'},
        'evidence_spans': spans, 'source_count': len(documents), 'document_ids': sorted(documents),
        'source_title': primary_document.title, 'text': primary_statement.text, 'not_a_financial_fact': True})
    return event
