"""Source-linked sector/company commentary, separate from numerical SQL truth."""
import json
from datetime import UTC,datetime
from sqlalchemy import select,or_
from app.models.document import Document,DocumentEvidenceTag,DocumentPage
from app.models.workstation import Instrument,DataSource
from app.providers.evidence.briefing_site import BASE
from app.providers.evidence.sources import bounded_http_fetch
from app.services.ingestion_persistence import source,store_artifact
from app.services.rag_service import create_document_from_pages,ParsedPage,content_hash
from app.services.news_retrieval import canonical_sector

URL=BASE+'/research.json'
SOURCE_NAME='Market research commentary'
VERSION='public-briefing-v1'


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
    result=[]
    for kind,symbol,sector,title,text,pointer in entries:
        doc=db.scalar(select(Document).where(Document.source_url==URL,Document.title==title,
            Document.content_hash==content_hash(text),Document.published_date==generated.date()))
        if not doc:
            doc=create_document_from_pages(db,[ParsedPage(1,text)],title=title,document_type='commentary',symbol=symbol,sector=sector,
                source_name=SOURCE_NAME,source_url=URL,published_date=generated.date(),artifact_id=artifact.id,
                source_tier_value=4,physical_pages=False,commit=False)
            from app.models.document import DocumentChunk
            for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id==doc.id)):
                chunk.metadata_json=json.dumps({**json.loads(chunk.metadata_json),'evidence_kind':'interpretation',
                    'analysis_scope':kind,'json_pointer':pointer,'generated_at':generated.isoformat(),'numerical_promotion':'prohibited'})
        result.append(doc.id)
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
    documents=db.scalars(query.order_by(Document.published_date.desc(),Document.created_at.desc()).limit(limit)).all()
    rows=[]
    for doc in documents:
        text=db.scalar(select(DocumentPage.text).where(DocumentPage.document_id==doc.id).order_by(DocumentPage.page_number).limit(1)) or ''
        rows.append({'id':doc.id,'symbol':doc.symbol,'sector':doc.sector,'published_date':str(doc.published_date),
            'text':text,'classification':'interpretation','source_name':SOURCE_NAME,'source_url':doc.source_url,'title':doc.title})
    return rows
