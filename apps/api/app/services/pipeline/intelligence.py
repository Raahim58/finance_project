"""Public, versioned intelligence sections reuse unchanged sourced evidence.

Narratives are verbatim evidence and deterministic SQL observations. No saved
model interpretation is automatically promoted to facts or used as an input.
"""
from datetime import UTC, datetime
from sqlalchemy import select
from app.models.document import Document
from app.models.pipeline import ArtifactPin, CompanyIntelligenceSection, DocumentEntityLink, EvidenceStatement, IntelligenceDependency
from app.models.workstation import Instrument
from app.services.company_snapshot import financial_rows, select_periods
from app.services.pipeline.runs import fingerprint
from app.services.financial_evidence_eligibility import secondary_financial_gap

SECTION_KEYS=('financial_performance','earnings_drivers','expansion','dividends','material_developments','sector_macro','risks','unresolved_questions')
EVENT_SECTIONS={'earnings':'earnings_drivers','expansion':'expansion','dividend':'dividends',
    'macro':'sector_macro','geopolitics':'sector_macro','disruption':'risks',
    'regulatory':'risks','financing':'material_developments','governance':'material_developments','ownership':'material_developments'}

def statement_dependency_version(statement):
    """Review and corrections matter even if an old extractor hash is unchanged."""
    return fingerprint({field:getattr(statement,field) for field in (
        'fingerprint','validation_status','text','kind','event_type','lifecycle',
        'attribution','topics','sentiment','subject_type','subject_key','supersedes_id',
        'period_start','period_end','accounting_basis','typed_value')})

def public_document(document):
    return bool(document and document.visibility=='public'
        and document.owner_user_id is None and document.portfolio_id is None
        and document.status not in ('revoked','superseded','failed'))

def refresh(db,instrument_id):
    instrument=db.get(Instrument,instrument_id)
    if not instrument: raise ValueError('instrument_not_found')
    docs=select(DocumentEntityLink.document_id).where(DocumentEntityLink.instrument_id==instrument_id,
        DocumentEntityLink.status=='validated')
    # Direct evidence only here. Sector/macro relationships are not guessed by
    # the model; the query-time broader lane remains separately labelled.
    statements=list(db.scalars(select(EvidenceStatement).join(Document,Document.id==EvidenceStatement.document_id)
        .where(EvidenceStatement.document_id.in_(docs),EvidenceStatement.subject_key==instrument.symbol,
            EvidenceStatement.validation_status=='validated',Document.visibility=='public',
            Document.portfolio_id.is_(None),Document.owner_user_id.is_(None),
            Document.status.not_in(('revoked','superseded','failed')))
        .order_by(Document.published_date.desc(),EvidenceStatement.id)))
    grouped={key:[] for key in SECTION_KEYS};sources={key:[] for key in SECTION_KEYS};dependencies={key:[] for key in SECTION_KEYS}
    facts=select_periods([fact for fact in financial_rows(db,instrument)
        if not fact.get('document_id') or public_document(db.get(Document,fact['document_id']))])
    grouped['financial_performance']=facts
    for fact in facts:
        dependencies['financial_performance'].append(('financial_value',fact['id'],fingerprint(fact)))
        document=db.get(Document,fact.get('document_id')) if fact.get('document_id') else None
        if document: dependencies['financial_performance'].append(('document',document.id,document.content_hash))
        sources['financial_performance'].append({'fact_id':fact['id'],'document_id':fact.get('document_id'),
            'underlying_id':f"financial_fact:{fact['id']}:v{fact.get('version',1)}",
            'version':fact.get('version',1),'quote_snippet':fact.get('source_name'),
            'title':document.title if document else None,
            'source_name':document.source_name if document else fact.get('source_name'),
            'source_url':fact.get('source_url') or (document.source_url if document else None),
            'page_number':fact.get('page_number')})
    for stmt in statements:
        key=EVENT_SECTIONS.get(stmt.event_type,'material_developments')
        if len(grouped[key])>=8: continue
        document=db.get(Document,stmt.document_id)
        grouped[key].append({'statement_id':stmt.id,'text':stmt.text,'kind':stmt.kind,'lifecycle':stmt.lifecycle,
            'attribution':stmt.attribution,'sentiment':stmt.sentiment,'published_date':str(document.published_date) if document.published_date else None})
        sources[key].append({'statement_id':stmt.id,'document_id':document.id,'source_url':document.source_url,
            'underlying_id':'evidence_statement:'+stmt.id+':'+statement_dependency_version(stmt),
            'quote_snippet':stmt.text,'source_name':document.source_name,'title':document.title})
        dependencies[key].append(('document',document.id,document.content_hash))
        dependencies[key].append(('statement',stmt.id,statement_dependency_version(stmt)))
    versions=[]
    for key in SECTION_KEYS:
        gaps=[] if grouped[key] else ['No validated evidence for this section.']
        if key=='financial_performance' and (secondary_gap:=secondary_financial_gap(db,instrument_id)):
            gaps.append(secondary_gap['detail'])
        if key=='unresolved_questions': gaps=['Interpretation and unresolved questions require reviewed synthesis.']
        if key=='sector_macro': gaps.append('Indirect company exposure is not inferred from sector keywords.')
        content={'evidence':grouped[key], 'basis':'SQL observations and verbatim source text; not an investment conclusion'}
        if key=='financial_performance':
            from app.ai.company_packet import financial_changes
            packet={'sections':{'facts':{'scope':{'instrument_id':instrument_id},'evidence_refs':[],
                'data':{'sections':[{'name':'company_facts','data':{'fundamentals':[dict(f,evidence_refs=[f['id']]) for f in facts]}}]}}}}
            changes,conflicts=financial_changes(packet)
            content['changes']=changes;content['conflicts']=conflicts
        # A reviewed dependency can change while rendered prose remains the
        # same. Reusing that section must not retain its obsolete dependency.
        digest=fingerprint([content,sources[key],gaps,sorted(set(dependencies[key]))])
        row=db.scalar(select(CompanyIntelligenceSection).where(CompanyIntelligenceSection.instrument_id==instrument_id,
            CompanyIntelligenceSection.section_key==key,CompanyIntelligenceSection.input_hash==digest))
        previous=db.scalar(select(CompanyIntelligenceSection).where(CompanyIntelligenceSection.instrument_id==instrument_id,
            CompanyIntelligenceSection.section_key==key,CompanyIntelligenceSection.is_selected.is_(True)).with_for_update())
        if previous and previous.id==(row.id if row else None): versions.append(row.id);continue
        if previous: previous.is_selected=False;db.flush()
        if row is None:
            row=CompanyIntelligenceSection(instrument_id=instrument_id,section_key=key,input_hash=digest,
                version=previous.version+1 if previous else 1,content=content,sources=sources[key],gaps=gaps,
                validation_status='source_grounded',effective_asof=datetime.now(UTC),is_selected=True)
            db.add(row);db.flush()
            for typ,identifier,version in set(dependencies[key]):
                db.add(IntelligenceDependency(section_id=row.id,dependency_type=typ,dependency_id=identifier,dependency_version=version))
            pinned_artifacts=set()
            for src in sources[key]:
                doc=db.get(Document,src.get('document_id')) if src.get('document_id') else None
                if doc and doc.artifact_id and doc.artifact_id not in pinned_artifacts and not db.get(ArtifactPin,(doc.artifact_id,'intelligence',row.id)):
                    db.add(ArtifactPin(artifact_id=doc.artifact_id,consumer_type='intelligence',consumer_id=row.id))
                    pinned_artifacts.add(doc.artifact_id)
        else: row.is_selected=True
        versions.append(row.id)
    db.flush();return versions

def read(db,instrument_id):
    result=[]
    instrument=db.get(Instrument,instrument_id)
    current_facts={f["id"]:fingerprint(f) for f in financial_rows(db,instrument)} if instrument else {}
    for row in db.scalars(select(CompanyIntelligenceSection).where(
            CompanyIntelligenceSection.instrument_id==instrument_id,CompanyIntelligenceSection.is_selected.is_(True))):
        stale=False
        for dep in db.scalars(select(IntelligenceDependency).where(IntelligenceDependency.section_id==row.id,
                IntelligenceDependency.dependency_type.in_(('document','financial_value','statement')))):
            if dep.dependency_type=='financial_value':
                if current_facts.get(dep.dependency_id)!=dep.dependency_version: stale=True;break
                continue
            if dep.dependency_type=='statement':
                statement=db.get(EvidenceStatement,dep.dependency_id)
                if (not statement or statement.validation_status!='validated'
                        or statement_dependency_version(statement)!=dep.dependency_version):
                    stale=True;break
                continue
            doc=db.get(Document,dep.dependency_id)
            if not public_document(doc) or doc.content_hash!=dep.dependency_version:
                stale=True;break
        result.append({'section':row.section_key,'version':row.version,
            'as_of':row.effective_asof.isoformat() if row.effective_asof else None,
            'content':{} if stale else row.content,'sources':[] if stale else row.sources,
            'gaps':[*row.gaps,*(['Source dependency changed; section requires refresh.'] if stale else [])],
            'state':'stale' if stale else 'source_grounded'})
    return result
