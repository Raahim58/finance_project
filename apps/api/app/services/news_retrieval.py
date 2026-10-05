"""Indexed evidence tags and bounded company/sector/broader retrieval."""
import re
import base64
import hashlib
import json
from collections import Counter
from sqlalchemy import select
from app.models.document import DocumentEvidenceTag
from app.models.workstation import Instrument
from app.ingestion.news_selection import classify_news, TOPIC_TERMS
from app.schemas.rag import RagSearchRequest

SECTOR_ALIASES = {
    'cement':'cement', 'fertilizer':'fertilizer', 'fertiliser':'fertilizer',
    'textile':'textile', 'oil':'energy', 'gas':'energy', 'refinery':'energy', 'power':'energy',
    'steel':'metals', 'engineering':'metals', 'technology':'technology',
    'transport':'shipping', 'bank':'banking', 'automobile':'automobile',
}


def canonical_sector(value):
    lowered=value.lower()
    return next((tag for fragment,tag in SECTOR_ALIASES.items() if fragment in lowered),lowered.strip())


def tag_document(db, document, text):
    inferred=classify_news(document.title,text)
    existing={(r.kind,r.value) for r in db.scalars(select(DocumentEvidenceTag).where(DocumentEvidenceTag.document_id==document.id))}
    tags={("sector",s,"text_match") for s in inferred['sectors']}
    tags.update(("topic",t,"text_match") for t in inferred['topics'])
    if document.sector: tags.add(('sector',canonical_sector(document.sector),'document_sector'))
    if document.symbol: tags.add(('company',document.symbol.upper(),'document_company'))
    for kind,value,basis in sorted(tags):
        if (kind,value) not in existing:
            db.add(DocumentEvidenceTag(document_id=document.id,kind=kind,value=value,basis=basis))
            existing.add((kind,value))
    db.flush()


def search_research_evidence(db,user,payload,*,public_only=False):
    from app.services.rag_service import search_rag, _query_symbols
    identity=hashlib.sha256(json.dumps({'user':user.id,'request':payload.model_dump(mode='json',exclude={'cursor'})},sort_keys=True).encode()).hexdigest()
    offsets={};seen=set();per_document=Counter()
    if payload.cursor:
        try:
            state=json.loads(base64.urlsafe_b64decode(payload.cursor))
            if state['scope']!=identity: raise ValueError('scope mismatch')
            if not isinstance(state['offsets'],dict) or not isinstance(state['seen'],list) or not isinstance(state['documents'],dict): raise ValueError('cursor shape')
            offsets=state['offsets'];seen=set(state['seen']);per_document=Counter(state['documents'])
            if (len(seen)>80 or any(not isinstance(v,int) or v<0 or v>200 for v in offsets.values())
                or any(not isinstance(v,int) or v<0 or v>2 for v in per_document.values())): raise ValueError('cursor bounds')
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError('Invalid research cursor; reuse the same search arguments') from exc
    symbols=payload.symbols or []
    if not symbols:
        symbols,ambiguous=_query_symbols(db,payload.query)
        if ambiguous:
            response=search_rag(db,None if public_only else user,RagSearchRequest(query=payload.query,portfolio_id=payload.portfolio_id,limit=payload.limit))
            return [],[],{'disambiguation':response.disambiguation.model_dump() if response.disambiguation else None}
    sectors=list(dict.fromkeys(canonical_sector(s) for s in payload.sectors or []))
    if symbols and not sectors:
        sectors=list(dict.fromkeys(canonical_sector(s) for s in db.scalars(select(Instrument.sector).where(Instrument.symbol.in_(symbols))) if s))
    topics=payload.topics or []
    base=dict(portfolio_id=payload.portfolio_id,date_from=payload.date_from,date_to=payload.date_to,
        document_types=payload.document_types,limit=min(25,payload.limit*2+1))
    lanes=[]
    if symbols: lanes.append(('company',dict(query=payload.query,symbols=symbols)))
    else: lanes.append(('requested',dict(query=payload.query,sectors=payload.sectors,topics=topics)))
    # Broader lanes opt out of symbol auto-resolution: a company name in the
    # prose query must not reinstate the very filter these lanes bypass.
    if payload.include_broader_context:
        clean=re.sub(r'\b(?:'+ '|'.join(re.escape(s) for s in symbols)+r')\b','',payload.query,flags=re.I) if symbols else payload.query
        if sectors: lanes.append(('sector',dict(query=clean+' '+' '.join(sectors),sector_tags=sectors,auto_symbols=False)))
        if symbols or topics:
            topics=topics or classify_news(payload.query)['topics'] or ['rates','inflation','fx','geopolitics']
            expanded=' '.join(term for topic in topics for term in TOPIC_TERMS.get(topic,(topic,)))
            lanes.append(('broader',dict(query=expanded+' '+clean,topics=topics,auto_symbols=False,document_types=['news','macro_report','policy_document'])))
    results=[];coverage={}
    for name,filters in lanes:
        request=RagSearchRequest(**{**base,**filters,'rank_offset':offsets.get(name,0)})
        response=search_rag(db,None if public_only else user,request)
        results.append((name,response.chunks))
        coverage[name]={'candidate_page_size':len(response.chunks),
            'returned':0,'has_more':response.audit.has_more,
            'date_from':str(payload.date_from) if payload.date_from else None,
            'date_to':str(payload.date_to) if payload.date_to else None}
    # Preserve lane diversity, but don't force irrelevant results: each lane
    # has already passed the existing relevance and citation checks.
    chosen=[];consumed=Counter();length=max((len(rows) for _,rows in results),default=0)
    for offset in range(length):
        for name,rows in results:
            if offset>=len(rows) or len(chosen)>=payload.limit: continue
            chunk=rows[offset]
            consumed[name]+=1
            if chunk.id in seen or per_document[chunk.document_id]>=2: continue
            seen.add(chunk.id);per_document[chunk.document_id]+=1;chosen.append((name,chunk))
            coverage[name]['returned']+=1
    for name,rows in results:
        coverage[name]['has_more']=coverage[name]['has_more'] or len(rows)>consumed[name]
        offsets[name]=offsets.get(name,0)+consumed[name]
    next_cursor=None
    if any(c['has_more'] for c in coverage.values()) and len(seen)<=70 and all(v<=190 for v in offsets.values()):
        next_cursor=base64.urlsafe_b64encode(json.dumps({'scope':identity,'offsets':offsets,
            'seen':sorted(seen),'documents':dict(per_document)},separators=(',',':')).encode()).decode()
    return chosen,[chunk.citation for _,chunk in chosen],{'groups':coverage,
        'next_cursor':next_cursor,
        'cursor_window_exhausted':next_cursor is None and any(c['has_more'] for c in coverage.values()),
        'coverage_note':'Matching stored evidence; not a claim of complete news coverage.'}
