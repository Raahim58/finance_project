"""Company-only deterministic selection. Originals remain queryable; no LLM here."""
import json
import re
from datetime import date
from sqlalchemy import select, or_
from app.domain.research_relevance import canonical, fingerprint
from app.models.document import Document, DocumentEvidenceTag
from app.models.workstation import FinancialFact, StandardizedFinancialFact, CorporateAction
from app.reasoning.projection import estimate_tokens
from app.ai.company_packet import financial_changes

VERSION = 'company-snapshot.v1'
TARGET_TOKENS = 5000


def select_periods(facts):
    """Per reporting basis: latest two annuals, latest interim + same span last year."""
    groups = {}
    for fact in facts:
        groups.setdefault(fact.get('accounting_basis'), []).append(fact)
    chosen = []
    for rows in groups.values():
        annual = sorted({(f.get('period_start'), f['period_end'], f.get('period_type')) for f in rows
                         if f.get('period_type') in ('annual', 'FY', 'year', 'yearly')}, key=lambda p:p[1], reverse=True)[:2]
        interim = sorted({(f.get('period_start'), f['period_end'], f.get('period_type')) for f in rows
                          if f.get('period_type') not in ('annual', 'FY', 'year', 'yearly')}, key=lambda p:p[1], reverse=True)
        selected = set(annual)
        if interim:
            latest = interim[0]
            selected.add(latest)
            # Explicit calendar shape, not simply the preceding interim row.
            match = next((p for p in interim[1:] if p[2] == latest[2] and p[0] and latest[0]
                          and int(p[1][:4]) == int(latest[1][:4])-1
                          and p[1][4:] == latest[1][4:] and p[0][4:] == latest[0][4:]
                          and int(p[0][:4]) == int(latest[0][:4])-1), None)
            if match:
                selected.add(match)
        chosen.extend(f for f in rows if (f.get('period_start'), f['period_end'], f.get('period_type')) in selected)
    return chosen


def financial_rows(db, instrument):
    today = date.today()
    filings = list(db.scalars(select(FinancialFact).where(
        FinancialFact.instrument_id == instrument.id, FinancialFact.period_end <= today,
        or_(FinancialFact.confidence.is_(None), FinancialFact.confidence > 0),
        or_(FinancialFact.filing_date.is_(None), FinancialFact.filing_date <= today))
        .order_by(FinancialFact.version.desc(), FinancialFact.id)))
    # Latest revisions per source; contradictory sources remain, never averaged.
    seen, rows = set(), []
    for f in filings:
        key = (f.taxonomy_key, f.period_start, f.period_end, f.period_type, f.unit, f.currency, f.consolidated, f.source_label, f.document_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append({'id':f.id, 'metric':f.taxonomy_key, 'value':str(f.value), 'unit':f.unit,
            'currency':f.currency, 'period_type':f.period_type,
            'period_start':str(f.period_start) if f.period_start else None, 'period_end':str(f.period_end),
            'accounting_basis':'consolidated' if f.consolidated else 'standalone',
            'document_id':f.document_id, 'page_number':f.page_number, 'source_name':f.source_label,
            'version':f.version})
    for f in db.scalars(select(StandardizedFinancialFact).where(
        StandardizedFinancialFact.instrument_id == instrument.id, StandardizedFinancialFact.quality_status == 'observed',
        StandardizedFinancialFact.period_end <= today).order_by(StandardizedFinancialFact.id)):
        rows.append({'id':f.id, 'metric':f.metric, 'value':str(f.value), 'unit':f.unit,
            'currency':f.currency, 'period_type':f.period_type, 'period_start':None,
            'period_end':str(f.period_end), 'accounting_basis':None, 'source_name':f.source, 'source_url':f.source_url})
    return rows


def dependency_hash(db, instrument):
    """SQL-only check; no embedding, generation or price calculation on page reads."""
    from app.models.workstation import MarketObservation, MacroObservation, CompanyScreeningSnapshot, NormalizedEvent, EventEntityLink, Event, NormalizedEventEvidence
    from app.models.market import MarketPrice, SectorDailyStats
    from app.services.news_retrieval import canonical_sector
    # Stable source versions: no clock bucket, so merely reopening never marks a brief dirty.
    versions = {
        'facts': select_periods(financial_rows(db, instrument)),
        'prices': [tuple(r) for r in db.execute(select(MarketObservation.id, MarketObservation.effective_at,
            MarketObservation.values_json, MarketObservation.artifact_id).where(MarketObservation.instrument_id == instrument.id,
            MarketObservation.is_selected.is_(True)).order_by(MarketObservation.id))],
        'legacy_prices': [tuple(r) for r in db.execute(select(MarketPrice.id, MarketPrice.trade_date, MarketPrice.close,
            MarketPrice.previous_close, MarketPrice.volume).where(MarketPrice.symbol == instrument.symbol).order_by(MarketPrice.id))],
        'screening': [tuple(r) for r in db.execute(select(CompanyScreeningSnapshot.id, CompanyScreeningSnapshot.metrics_json)
            .where(CompanyScreeningSnapshot.instrument_id == instrument.id).order_by(CompanyScreeningSnapshot.as_of_date.desc()).limit(1))],
        'macro': [tuple(r) for r in db.execute(select(MacroObservation.id, MacroObservation.value, MacroObservation.revision,
            MacroObservation.effective_date).where(MacroObservation.is_selected.is_(True)).order_by(MacroObservation.id))],
        'sector': [tuple(r) for r in db.execute(select(SectorDailyStats.id, SectorDailyStats.trade_date, SectorDailyStats.total_value,
            SectorDailyStats.average_change_percent).order_by(SectorDailyStats.trade_date.desc()).limit(100))],
    }
    # Tags allow sector/global articles without a direct company name. Include text/version corrections.
    tags = select(DocumentEvidenceTag.document_id).where(or_(
        (DocumentEvidenceTag.kind == 'company') & (DocumentEvidenceTag.value == instrument.symbol),
        (DocumentEvidenceTag.kind == 'sector') & (DocumentEvidenceTag.value == canonical_sector(instrument.sector or '')),
        (DocumentEvidenceTag.kind == 'topic') & DocumentEvidenceTag.value.in_(('rates','inflation','fx','geopolitics'))))
    docs = [tuple(row) for row in db.execute(select(Document.id, Document.content_hash, Document.parsed_at,
            Document.published_date, Document.title, Document.source_url).where(
            Document.visibility == 'public', Document.portfolio_id.is_(None), Document.data_status == 'observed',
            or_(Document.symbol == instrument.symbol, Document.sector == instrument.sector, Document.id.in_(tags)))
        .order_by(Document.published_date.desc(), Document.id).limit(100))]
    actions = [tuple(row) for row in db.execute(select(CorporateAction.id, CorporateAction.action_type,
        CorporateAction.effective_date, CorporateAction.details_json, CorporateAction.artifact_id).where(CorporateAction.instrument_id == instrument.id))]
    events = [tuple(row) for row in db.execute(select(Event.id, Event.title, Event.occurred_at,
        NormalizedEvent.classification_status, NormalizedEvent.materiality, NormalizedEvent.details_json)
        .join(EventEntityLink,EventEntityLink.event_id == Event.id)
        .join(NormalizedEventEvidence,NormalizedEventEvidence.raw_event_id == Event.id)
        .join(NormalizedEvent,NormalizedEvent.id == NormalizedEventEvidence.normalized_event_id)
        .where(EventEntityLink.entity_type == 'instrument', EventEntityLink.entity_key == instrument.symbol)
        .order_by(Event.id))]
    return fingerprint({'version':VERSION,'versions':versions,'documents':docs,'actions':actions,'events':events})


def excerpt(text):
    """Whole adjacent sentences only; explicitly mark omission, retain originals."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    selected_indices = set()
    words = 0
    for i,sentence in enumerate(sentences):
        if words >= 100: break
        selected_indices.add(i); words += len(sentence.split())
    # Never silently drop a qualification merely because it comes later in a chunk.
    qualification = re.compile(r'(?i)\b(however|although|nevertheless|despite|in contrast|not approved|not confirmed|subject to|depends on|may not|no guarantee)\b')
    for i,sentence in enumerate(sentences):
        if qualification.search(sentence):
            selected_indices.update(range(max(0,i-1),min(len(sentences),i+2)))
    selected = []
    previous = None
    for i in sorted(selected_indices):
        if previous is not None and i != previous+1: selected.append('…')
        selected.append(sentences[i]); previous=i
    return ' '.join(selected), len(selected_indices) < len(sentences)


def build_snapshot(db, user, instrument):
    from app.tools.research_tools import _company_sections, CompanySectionsInput, _search, ResearchInput
    from app.tools.market_tools import _latest, MarketLatestInput
    from app.tools.registry import expand_model_data, normalize_json
    sources = {}
    def source(row):
        # One canonical document/page source, no duplicated excerpt or ingestion payload.
        row = {**row,'source_name':row.get('source_name') or row.get('source'),'published_at':row.get('published_at') or row.get('as_of')}
        clean = {k:row.get(k) for k in ('document_id','page_number','source_name','source_url','title','published_at') if row.get(k) is not None}
        key = fingerprint(clean)
        ref = next((r for r,v in sources.items() if fingerprint(v) == key), None)
        if ref is None:
            ref = f'S{len(sources)+1}'; sources[ref] = clean
        return ref
    def section(name):
        result = _company_sections(db, user, CompanySectionsInput(instrument_id=instrument.id,
            sections=[name], limit=5, sector_comparison_limit=5 if name == 'sector' else 0))
        result = normalize_json(result)
        data = expand_model_data(result.get('data')) or {}
        parts = data.get('sections') or []
        part = parts[0] if parts else {}
        mapping = {s.get('evidence_id') or s.get('id'):source(s) for s in result.get('sources',[])}
        def remap(value):
            if isinstance(value,dict):
                return {k:(mapping.get(v,v) if k == 'source_ref' and isinstance(v,str) else
                    [mapping.get(r,r) for r in v] if k in ('source_refs','evidence_refs') and isinstance(v,list) else remap(v)) for k,v in value.items()}
            if isinstance(value,list): return [remap(v) for v in value]
            return value
        return {'state':part.get('state',result.get('status')), 'as_of':part.get('as_of'),
                'data':remap(part.get('data')), 'source_refs':[source(s) for s in result.get('sources',[])],
                'errors':part.get('errors',[])}
    all_facts = financial_rows(db, instrument)
    facts = select_periods(all_facts)
    docs = {d.id:d for d in db.scalars(select(Document).where(Document.id.in_([f.get('document_id') for f in facts if f.get('document_id')])))}
    for fact in facts:
        doc = docs.get(fact.get('document_id'))
        fact['evidence_refs'] = [source({'document_id':fact.pop('document_id',None),
            'page_number':fact.pop('page_number',None), 'source_name':fact.pop('source_name',None),
            'source_url':fact.pop('source_url',None) or (doc.source_url if doc else None),
            'title':doc.title if doc else None})]
        fact.pop('version',None)
    packet = {'sections':{'facts':{'scope':{'instrument_id':instrument.id}, 'evidence_refs':[],
        'data':{'sections':[{'name':'company_facts','data':{'fundamentals':facts}}]}}}}
    changes, conflicts = financial_changes(packet)
    for row in changes:
        row.pop('instrument_id',None)
    news = normalize_json(_search(db,user,ResearchInput(query=f'{instrument.symbol} {instrument.name} earnings dividends expansion insider transactions valuation sector macro risks',
        symbols=[instrument.symbol], include_broader_context=True, limit=6),public_only=True))
    lookup = {s['id']:s for s in news.get('sources',[]) if s.get('id')}
    events = []
    for chunk in (expand_model_data(news.get('data')) or {}).get('chunks',[]):
        text, omitted = excerpt(chunk.get('text') or '')
        events.append({'id':chunk['id'],'date':chunk.get('published_date'),'lane':chunk.get('group'),
            'text':text,'kind':chunk.get('evidence_kind'),'excerpt_omits_detail':omitted,
            'evidence_refs':[source(lookup.get(chunk.get('source_ref'),{}))]})
    market = normalize_json(_latest(db,user,MarketLatestInput(instrument_id=instrument.id)))
    market_data = expand_model_data(market.get('data')) or {}
    for k in ('instrument_id','symbol','source_ref'):
        market_data.pop(k,None)
    market_data['evidence_refs'] = [source(s) for s in market.get('sources',[])]
    risk, sector, macro, disclosed = (section(name) for name in ('market_risk','sector','macro','events'))
    # The market section already carries prices; keep only numerical risk + method here.
    risk['data'] = {k:v for k,v in (risk.get('data') or {}).items() if k in
        ('risk_metrics','risk_calculation_as_of','risk_method','screening_metrics','screening_as_of')}
    from app.models.workstation import SourceArtifact, DataSource
    actions = []
    for action in db.scalars(select(CorporateAction).where(CorporateAction.instrument_id == instrument.id,
            CorporateAction.effective_date <= date.today()).order_by(CorporateAction.effective_date.desc()).limit(10)):
        artifact = db.get(SourceArtifact,action.artifact_id) if action.artifact_id else None
        publisher = db.get(DataSource,artifact.data_source_id) if artifact else None
        actions.append({'id':action.id,'type':action.action_type,'effective_date':str(action.effective_date),
            'details':json.loads(action.details_json),'source_backed':bool(artifact),
            'evidence_refs':[source({'source_name':publisher.name if publisher else None,'source_url':artifact.source_url if artifact else None})]})
    snapshot = {'version':VERSION, 'company':{'instrument_id':instrument.id,'symbol':instrument.symbol,'name':instrument.name,'sector':instrument.sector},
        'financials':facts,'changes':changes,'conflicts':conflicts,'market':market_data,
        'corporate_actions':actions,'risk':risk,'sector':sector,'macro':macro,'disclosures':disclosed,'news':events,'sources':sources,
        'coverage':{'financial_rows_selected':len(facts),'financial_rows_available':len(all_facts),
            'news':(expand_model_data(news.get('data')) or {}).get('coverage'),
            'selection':'Latest two annual periods and latest interim plus comparable prior-year interim per reporting basis. News is bounded retrieval, not complete coverage.',
            'detail_tools':['research.company_sections','research.search','market.series'],
            'live_web_search':'not_configured'},
        'missing_data':[]}
    for name,value in (('risk',risk),('sector',sector),('macro',macro),('disclosures',disclosed)):
        if value['state'] in ('missing','incomplete','not_evaluated','stale'):
            snapshot['missing_data'].append({'section':name,'state':value['state'],'errors':value['errors']})
    if not facts: snapshot['missing_data'].append({'section':'financials','state':'missing'})
    if not changes: snapshot['missing_data'].append({'section':'changes','state':'no_compatible_pair'})
    if market.get('status') != 'ok': snapshot['missing_data'].append({'section':'market','state':market.get('status')})
    if not events: snapshot['missing_data'].append({'section':'news','state':news.get('status')})
    # Measurement is outside the hashed factual payload; exceeding the target never truncates facts.
    from app.services.research_generation_service import brief_projection
    count = estimate_tokens(brief_projection(snapshot))
    snapshot['size'] = {'estimated_tokens':count,'serialized_bytes':len(canonical(brief_projection(snapshot)).encode()),
        'target_tokens':TARGET_TOKENS,'over_target':count>TARGET_TOKENS}
    return snapshot
