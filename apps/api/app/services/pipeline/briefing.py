"""Source-linked sector/company commentary, separate from numerical SQL truth."""
import json
from datetime import UTC,datetime
from sqlalchemy import select,or_
from app.models.document import Document,DocumentChunk,DocumentEvidenceTag,DocumentPage
from app.models.workstation import Instrument,SourceArtifact
from app.providers.evidence.briefing_site import BASE
from app.providers.evidence.sources import bounded_http_fetch
from app.services.ingestion_persistence import source,store_artifact
from app.services.rag_service import create_document_from_pages,ParsedPage,content_hash
from app.services.news_retrieval import canonical_sector

URL=BASE+'/research.json'
SOURCE_NAME='Market research commentary'
VERSION='public-briefing-v1'


def _metadata(db,document):
    raw=db.scalar(select(DocumentChunk.metadata_json).where(DocumentChunk.document_id==document.id)
        .order_by(DocumentChunk.chunk_index).limit(1))
    return json.loads(raw or '{}')


def _section_identity(document,metadata):
    scope=metadata.get('analysis_scope') or ('company' if document.symbol else 'sector' if document.sector else 'overview')
    subject=document.symbol if scope=='company' else canonical_sector(document.sector or '') if scope=='sector' else 'market'
    return (scope,subject)


def _utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def _edition(db,document,metadata):
    artifact=db.get(SourceArtifact,document.artifact_id) if document.artifact_id else None
    generated=datetime.fromisoformat(metadata['generated_at']) if metadata.get('generated_at') else (
        artifact.effective_at if artifact and artifact.effective_at else datetime.combine(document.published_date or datetime.min.date(),datetime.min.time()))
    captured=artifact.retrieved_at if artifact else document.created_at
    return (_utc(generated),_utc(captured) or datetime.min.replace(tzinfo=UTC),document.artifact_id or document.id)


def capture(db, *, fetcher=bounded_http_fetch):
    raw,final_url,content_type,_=fetcher(URL)
    payload=json.loads(raw);note=payload.get('research_note')
    if not isinstance(note,dict): raise ValueError('briefing_research_contract_changed')
    generated=datetime.fromisoformat(payload['generated_at_pkt']).astimezone(UTC)
    publisher=source(db,SOURCE_NAME,'commentary',BASE,50,1440,'Public analyst interpretation; source-linked news is ingested independently. No numeric facts are promoted from this feed.')
    artifact=store_artifact(db,publisher,raw,url=final_url,method='GET',parser_version=VERSION,content_type=content_type,effective_at=generated,lossless=True)
    entries=[]
    if note.get('executive_summary'):
        entries.append(('overview',None,None,note.get('title') or 'Morning market analysis',note['executive_summary'],'/research_note/executive_summary'))
    for index,row in enumerate(note.get('sector_highlights',[])):
        sector=str(row.get('sector') or '').strip();bullets=row.get('bullets') or []
        if sector and bullets:
            text='Sector: '+sector+'\nOutlook (analyst interpretation): '+str(row.get('outlook') or 'unspecified')+'\n'+'\n'.join(str(b) for b in bullets)
            entries.append(('sector',None,sector,sector+' — morning analysis',text,f'/research_note/sector_highlights/{index}'))
    for index,row in enumerate(note.get('stocks_to_watch',[])):
        symbol=str(row.get('ticker') or '').upper();reason=str(row.get('reason') or '').strip()
        instrument=db.scalar(select(Instrument).where(Instrument.symbol==symbol))
        if instrument and reason:
            text='Company: '+symbol+'\nOutlook (analyst interpretation): '+str(row.get('outlook') or 'unspecified')+'\n'+reason
            entries.append(('company',symbol,instrument.sector,symbol+' — morning analysis',text,f'/research_note/stocks_to_watch/{index}'))
    result=[];selected={}
    for kind,symbol,sector,title,text,pointer in entries:
        matches=db.scalars(select(Document).where(Document.source_url==URL,Document.title==title,
            Document.content_hash==content_hash(text),Document.published_date==generated.date(),
            Document.artifact_id==artifact.id)).all()
        doc=next((match for match in matches if _metadata(db,match).get('json_pointer')==pointer),None)
        if not doc:
            doc=create_document_from_pages(db,[ParsedPage(1,text)],title=title,document_type='commentary',symbol=symbol,sector=sector,
                source_name=SOURCE_NAME,source_url=URL,published_date=generated.date(),artifact_id=artifact.id,
                source_tier_value=4,physical_pages=False,commit=False)
            for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id==doc.id)):
                chunk.metadata_json=json.dumps({**json.loads(chunk.metadata_json),'evidence_kind':'interpretation',
                    'analysis_scope':kind,'json_pointer':pointer,'generated_at':generated.isoformat(),'numerical_promotion':'prohibited'})
        result.append(doc.id)
        selected.setdefault(_section_identity(doc,{'analysis_scope':kind}),[]).append(doc)
    # A corrected edition replaces only the matching subject/scope on its
    # publication day. Different companies, sectors and sections in one edition
    # survive; earlier dated editions remain available for historical retrieval.
    # Artifact capture time resolves equal generated_at revisions and prevents
    # replaying a known old artifact from resurrecting its withdrawn commentary.
    previous=db.scalars(select(Document).where(Document.source_url==URL,Document.source_name==SOURCE_NAME,
        Document.document_type=='commentary',Document.published_date==generated.date(),Document.status=='parsed',
        Document.visibility=='public',Document.owner_user_id.is_(None),Document.portfolio_id.is_(None))).all()
    for old in previous:
        current=selected.get(_section_identity(old,_metadata(db,old)))
        if not current or old.id in result: continue
        old_edition=_edition(db,old,_metadata(db,old));new_edition=_edition(db,current[0],_metadata(db,current[0]))
        if old_edition<new_edition: old.status='superseded'
        elif old_edition>new_edition:
            for document in current: document.status='superseded'
    db.flush();return {'document_ids':result,'generated_at':generated.isoformat(),'classification':'extra_unverified_analysis','canonical_financial_facts_written':0}


def read(db, *, symbols=None,sectors=None,limit=8):
    query=select(Document).where(Document.source_name==SOURCE_NAME,Document.document_type=='commentary',
        Document.visibility=='public',Document.owner_user_id.is_(None),Document.portfolio_id.is_(None),Document.status=='parsed')
    filters=[]
    if symbols: filters.append(Document.symbol.in_(symbols))
    if sectors:
        tagged=select(DocumentEvidenceTag.document_id).where(DocumentEvidenceTag.kind=='sector',DocumentEvidenceTag.value.in_([canonical_sector(s) for s in sectors]))
        filters.append(Document.id.in_(tagged))
    if filters: query=query.where(or_(*filters))
    documents=db.scalars(query).all()
    decorated=[(doc,_metadata(db,doc)) for doc in documents]
    decorated.sort(key=lambda entry:_edition(db,*entry),reverse=True)
    editions={};selected=[]
    for document,metadata in decorated:
        identity=_section_identity(document,metadata);edition=_edition(db,document,metadata)
        if identity not in editions: editions[identity]=edition
        if editions[identity]==edition: selected.append((document,metadata))
    rows=[]
    for doc,metadata in selected[:max(0,limit)]:
        text=db.scalar(select(DocumentPage.text).where(DocumentPage.document_id==doc.id).order_by(DocumentPage.page_number).limit(1)) or ''
        rows.append({'id':doc.id,'symbol':doc.symbol,'sector':doc.sector,'published_date':str(doc.published_date),
            'text':text,'classification':'interpretation','source_name':SOURCE_NAME,'source_url':doc.source_url,'title':doc.title,
            'generated_at':metadata.get('generated_at'),'artifact_id':doc.artifact_id,'json_pointer':metadata.get('json_pointer')})
    return rows
