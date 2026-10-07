"""Classification validation, semantic clustering with blockers, record reads and backfill."""
import json
from datetime import date
import httpx
import pytest
from sqlalchemy import func, select
from app.core.security import encrypt_secret
from app.db.session import SessionLocal
from app.models.pipeline import (DocumentClassification, EnrichmentAttempt, EventClusterFeature, EventDocumentLink,
    EvidenceStatement, IngestionStageRun, ServiceCredential)
from app.models.workstation import Instrument, NormalizedEvent
from app.schemas.pipeline import ArticleClassification
from app.services import rag_service
from app.services.pipeline import runs
from app.services.pipeline.classification import (MODEL_VERSION, RULES_VERSION, EntityIndex, canonical_period, classify,
    supported_date, validate_event)
from app.services.pipeline.event_reads import event_records
from app.services.pipeline.events import build
from app.services.pipeline.linking import link
from app.services.pipeline.parsing import sections
from app.services.pipeline.statements import extract
from app.services.rag_service import ParsedPage, create_document_from_pages


def instruments(db):
    luck = Instrument(symbol='LUCK', name='Lucky Cement Limited', sector='Cement')
    ogdc = Instrument(symbol='OGDC', name='Oil and Gas Development Company', sector='Oil & Gas Exploration Companies')
    db.add_all([luck, ogdc]);db.flush()
    return luck, ogdc


def article(db, text, *, title='Cement news', published=date(2026, 10, 1), kind='news', url=None, tier=3):
    doc = create_document_from_pages(db, [ParsedPage(1, text)], title=title, document_type=kind, symbol=None,
        source_name='Publisher', source_url=url or 'https://publisher.test/'+str(abs(hash(text))), published_date=published, commit=False)
    doc.source_tier = tier
    sections(db, doc.id);link(db, doc.id)
    return doc


@pytest.fixture
def vectors(monkeypatch):
    """Embeddings keyed by phrase so merge logic is tested independently of the model."""
    table = {}
    def embed(texts):
        out = []
        for text in texts:
            key = next((k for k in table if k in text), None)
            out.append(table[key] if key else [0.0]*383+[1.0])
        return out
    monkeypatch.setattr(rag_service, 'embed_texts', embed)
    return table


def model_output(section_id, **event):
    base = dict(entities=['LUCK'], event_type='expansion', kind='secondary_report', lifecycle='announced', direction='new',
        event_date=None, reporting_period=None, counterparties=[], amounts=[], topics=['capacity'], sentiment=None,
        evidence=[{'section_id': section_id, 'quote': 'Lucky Cement Limited will add a new cement line.'}])
    base.update(event)
    return ArticleClassification.model_validate({'events': [base]}).events[0]


def test_period_and_date_support_are_source_bound():
    assert canonical_period('1QFY26') == canonical_period('first quarter of FY2026') == 'Q1-FY2026'
    assert canonical_period('FY25') == canonical_period('fiscal year 2025') == 'FY2025'
    assert canonical_period('the period ended June') is None
    assert supported_date('2026-10-03', 'The board met on October 3, 2026.', date(2026, 10, 4)) == date(2026, 10, 3)
    assert supported_date('2026-10-03', 'The board met on 3rd Oct.', date(2026, 10, 4)) == date(2026, 10, 3)
    assert supported_date('2026-10-03', 'The board met recently.', date(2026, 10, 4)) is None
    assert supported_date('2025-10-03', 'The board met on October 3, 2026.', date(2026, 10, 4)) is None


def test_validation_keeps_only_source_supported_fields():
    with SessionLocal() as db:
        instruments(db)
        doc = article(db, 'Lucky Cement Limited will add a new cement line. It reportedly costs Rs 30 billion in FY26.')
        parts = {s.id: s for s in sections(db, doc.id)}
        section = next(iter(parts))
        entities = EntityIndex(db, doc, '\n'.join(s.text for s in parts.values()))
        event = model_output(section, entities=['Lucky Cement Limited', 'NOTSTORED'], kind='reported_fact', lifecycle='completed',
            event_date={'value': '2026-10-01', 'quote': 'Lucky Cement Limited will add a new cement line.'},
            reporting_period={'value': 'FY26', 'quote': 'It reportedly costs Rs 30 billion in FY26.'},
            amounts=[{'value': '30', 'unit': 'PKR billion', 'quote': 'It reportedly costs Rs 30 billion in FY26.'},
                     {'value': '45', 'unit': 'PKR billion', 'quote': 'It reportedly costs Rs 30 billion in FY26.'}],
            counterparties=['Invented Bank'],
            sentiment={'subject_key': 'LUCK', 'aspect': 'demand', 'direction': 'positive', 'horizon': 'forward', 'quote': 'Demand will boom.'},
            evidence=[{'section_id': section, 'quote': 'Lucky Cement Limited will add a new cement line.'},
                      {'section_id': section, 'quote': 'A quote that is not in the article.'}])
        cleaned = validate_event(event, parts, entities, doc, official=False)
        assert cleaned.entities == ['LUCK']
        assert cleaned.kind == 'secondary_report'  # Publisher text is never certified as an issuer fact.
        assert cleaned.event_date is None  # The quote has no date.
        assert cleaned.reporting_period.value == 'FY26'
        assert [a.value for a in cleaned.amounts] == ['30']
        assert cleaned.counterparties == [] and cleaned.sentiment is None
        assert [s.quote for s in cleaned.evidence] == ['Lucky Cement Limited will add a new cement line.']
        missing = model_output(section, evidence=[{'section_id': section, 'quote': 'Fabricated.'}])
        assert validate_event(missing, parts, entities, doc, official=False) is None


def test_rules_classification_is_versioned_idempotent_and_supersedes_old_statements():
    with SessionLocal() as db:
        luck, _ = instruments(db)
        doc = article(db, 'Lucky Cement Limited announced a dividend of Rs 5 per share. Lucky Cement Limited plans expansion of capacity.')
        legacy = extract(db, doc.id)
        assert legacy
        first = classify(db, doc.id)
        assert first['method'] == 'rules' and first['statements']
        assert classify(db, doc.id)['statements'] == first['statements']
        assert db.scalar(select(func.count()).select_from(DocumentClassification)) == 1
        statuses = {s.id: s.validation_status for s in db.scalars(select(EvidenceStatement))}
        assert all(statuses[i] == 'superseded' for i in legacy)
        rows = list(db.scalars(select(EvidenceStatement).where(EvidenceStatement.extractor_version == RULES_VERSION)))
        assert {r.event_type for r in rows} == {'dividend', 'expansion'}
        dividend = next(r for r in rows if r.event_type == 'dividend')
        assert dividend.kind == 'secondary_report' and dividend.typed_value['sectors'] == ['Cement']
        assert dividend.typed_value['amounts'][0]['basis'] == 'attributed_claim'


def test_differently_worded_reports_merge_into_one_record(vectors):
    vectors['new cement line'] = vectors['additional production line'] = [1.0]+[0.0]*383
    with SessionLocal() as db:
        instruments(db)
        first = article(db, 'Lucky Cement Limited plans a new cement line to expand capacity.', url='https://a.test/1')
        second = article(db, 'Lucky Cement Limited is building an additional production line, adding capacity.',
            url='https://b.test/2', published=date(2026, 10, 3))
        for doc in (first, second):
            classify(db, doc.id);build(db, doc.id)
        events = list(db.scalars(select(NormalizedEvent).where(NormalizedEvent.classification_status == 'classified')))
        assert len(events) == 1
        details = json.loads(events[0].details_json)
        assert details['source_count'] == 2 and len(details['evidence_spans']) == 2
        assert {s['document_id'] for s in details['evidence_spans']} == {first.id, second.id}
        records = event_records(db, symbols=['LUCK'])
        assert len(records) == 1 and records[0]['event_type'] == 'expansion'
        assert len(records[0]['raw_event_ids']) == 2


@pytest.mark.parametrize('second_text', [
    'Lucky Cement Limited reported profit growth in 1QFY26, higher by 20%.',   # different period
    'Lucky Cement Limited reported profit fell in 4QFY25, lower by 12%.',      # opposite direction + period
])
def test_similar_text_with_conflicting_facts_does_not_merge(vectors, second_text):
    vectors['profit'] = [1.0]+[0.0]*383
    with SessionLocal() as db:
        instruments(db)
        first = article(db, 'Lucky Cement Limited reported profit growth in 4QFY25, higher by 20%.', url='https://a.test/p')
        second = article(db, second_text, url='https://b.test/p', published=date(2026, 10, 2))
        for doc in (first, second):
            classify(db, doc.id);build(db, doc.id)
        assert db.scalar(select(func.count()).select_from(NormalizedEvent)) == 2


def test_conflicting_amounts_block_merge(vectors):
    vectors['dividend'] = [1.0]+[0.0]*383
    with SessionLocal() as db:
        instruments(db)
        for text, url in (('Lucky Cement Limited announced a dividend of Rs 5 per share.', 'https://a.test/d'),
                          ('Lucky Cement Limited announced a dividend of Rs 8 per share.', 'https://b.test/d')):
            doc = article(db, text, url=url);classify(db, doc.id);build(db, doc.id)
        assert db.scalar(select(func.count()).select_from(NormalizedEvent)) == 2


def test_proposal_then_approval_is_one_event_with_history(vectors):
    vectors['acquisition'] = [1.0]+[0.0]*383
    with SessionLocal() as db:
        instruments(db)
        proposed = article(db, 'Lucky Cement Limited submitted an expression of interest for the acquisition, subject to due diligence.',
            url='https://a.test/eoi', published=date(2026, 9, 28))
        completed = article(db, 'Lucky Cement Limited completed the acquisition.', url='https://b.test/ok')
        for doc in (proposed, completed):
            classify(db, doc.id);build(db, doc.id)
        events = list(db.scalars(select(NormalizedEvent).where(NormalizedEvent.classification_status == 'classified')))
        assert len(events) == 1
        details = json.loads(events[0].details_json)
        assert details['lifecycle'] == 'completed'
        assert [(h['lifecycle'], h['document_id']) for h in details['lifecycle_history']] == [
            ('proposed', proposed.id), ('completed', completed.id)]


def catalog_and_completion(content, status=200):
    model = 'nvidia/nemotron-3-super-120b-a12b:free'
    def handler(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': model, 'pricing': {'prompt': '0', 'completion': '0'},
                'supported_parameters': ['response_format', 'structured_outputs']}]})
        if status != 200: return httpx.Response(status)
        return httpx.Response(200, json={'model': model, 'usage': {'cost': 0},
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]})
    return httpx.MockTransport(handler)


def model_ready(db):
    db.add(ServiceCredential(purpose='pipeline_enrichment', provider='openrouter', secret_encrypted=encrypt_secret('sk-test'), active=True))
    run = runs.enqueue(db, 'classify', 'document:x', {'document_id': 'x'});run.attempt_count = 1;db.flush()
    return run


def test_model_classification_is_validated_and_never_overwritten_by_rules():
    with SessionLocal() as db:
        instruments(db)
        doc = article(db, 'Lucky Cement Limited will add a new cement line. Analysts expect demand to stay firm.')
        section = sections(db, doc.id)[0].id
        run = model_ready(db)
        output = {'events': [model_output(section).model_dump(mode='json'),
            model_output(section, evidence=[{'section_id': section, 'quote': 'Not in source.'}]).model_dump(mode='json')]}
        result = classify(db, doc.id, run=run, allow_model=True, transport=catalog_and_completion(output))
        assert result['method'] == 'model' and len(result['statements']) == 1
        assert '1_events_without_source_support' in result['gaps']
        assert db.scalar(select(EnrichmentAttempt.status)) == 'completed'
        assert classify(db, doc.id)['method'] == 'model'  # Rules replay reuses model output.
        row = db.scalar(select(DocumentClassification))
        assert row.classifier_version == MODEL_VERSION and 'sk-test' not in json.dumps(row.output)


def test_model_quota_falls_back_to_rules_and_stays_upgradeable():
    from app.jobs.classify_backfill import pending
    with SessionLocal() as db:
        instruments(db)
        doc = article(db, 'Lucky Cement Limited announced a dividend.')
        run = model_ready(db)
        result = classify(db, doc.id, run=run, allow_model=True, transport=catalog_and_completion({}, status=429))
        assert result['method'] == 'rules' and 'free_provider_quota_or_capacity' in result['gaps']
        assert [d.id for d in pending(db, target=MODEL_VERSION)] == [doc.id]
        assert pending(db, target=RULES_VERSION) == []


def test_backfill_queues_unclassified_documents_once():
    from app.jobs.classify_backfill import enqueue_documents, pending
    with SessionLocal() as db:
        instruments(db)
        parsed = article(db, 'Lucky Cement Limited announced a dividend.')
        raw = create_document_from_pages(db, [ParsedPage(1, 'Lucky Cement Limited plans expansion.')], title='Raw',
            document_type='news', source_name='Publisher', source_url='https://raw.test', published_date=date(2026, 10, 1), commit=False)
        docs = pending(db, target=RULES_VERSION)
        assert {d.id for d in docs} == {parsed.id, raw.id}
        assert enqueue_documents(db, docs, target=RULES_VERSION) == {'classify': 1, 'sections': 1}
        enqueue_documents(db, docs, target=RULES_VERSION)
        assert db.scalar(select(func.count()).select_from(IngestionStageRun)) == 2
        classify(db, parsed.id)
        assert [d.id for d in pending(db, target=RULES_VERSION)] == [raw.id]


def test_reads_filter_by_entity_and_type_and_rank(vectors):
    with SessionLocal() as db:
        instruments(db)
        old = article(db, 'Lucky Cement Limited announced a dividend of Rs 2 per share.', url='https://a.test/o', published=date(2025, 1, 2))
        new = article(db, 'Lucky Cement Limited plans expansion of capacity.', url='https://a.test/n', published=date(2026, 10, 1))
        other = article(db, 'Oil and Gas Development Company announced a dividend of Rs 3 per share.', url='https://a.test/x')
        for doc in (old, new, other):
            classify(db, doc.id);build(db, doc.id)
        luck = event_records(db, symbols=['luck'])
        assert [r['event_type'] for r in luck] == ['expansion', 'dividend']
        assert luck[0]['rank_score'] > luck[1]['rank_score']
        assert [r['subjects'][0]['subject_key'] for r in event_records(db, event_types=['dividend'])] == ['OGDC', 'LUCK']


def test_worker_chain_links_then_classifies_then_builds_and_refreshes():
    from app.jobs.pipeline_tasks import perform
    with SessionLocal() as db:
        luck, _ = instruments(db)
        doc = article(db, 'Lucky Cement Limited plans expansion of capacity.')
        def stage(name):
            run = runs.enqueue(db, name, 'document:'+doc.id, {'document_id': doc.id});db.flush()
            return perform(db, run)
        assert [c[0] for c in stage('link')[1]] == ['classify']
        output, children = stage('classify')
        assert output['method'] == 'rules' and [c[0] for c in children] == ['events']
        output, children = stage('events')
        assert output['events'] and [c[2]['instrument_id'] for c in children] == [luck.id]
        assert db.scalar(select(func.count()).select_from(EventClusterFeature)) == 1
        assert db.scalar(select(func.count()).select_from(EventDocumentLink)) == 1
