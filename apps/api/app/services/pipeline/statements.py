"""Rules retain source sentences; optional model proposals must pass quote checks."""
import re
from sqlalchemy import select
from app.models.document import Document
from app.models.pipeline import DocumentEntityLink, DocumentSection, EvidenceStatement, StatementEvidence
from app.models.workstation import Instrument
from app.schemas.pipeline import StatementBatch, StatementCandidate
from app.ingestion.news_selection import classify_news
from app.services.pipeline.runs import fingerprint

VERSION='statements-v1'
EVENT_TERMS={
 'earnings':r'\b(earnings|profit|revenue|sales)\b', 'dividend':r'\bdividend\b',
 'expansion':r'\b(capacity|expansion|plant|commissioned|commissioning)\b',
 'financing':r'\b(debt|loan|financing|bond|sukuk)\b', 'regulatory':r'\b(regulator|court|approved|approval)\b',
 'governance':r'\b(chairman|board|chief executive|resign)\b',
 'macro':r'\b(inflation|policy rate|reserves|exchange rate)\b',
 'geopolitics':r'\b(sanctions|war|conflict|red sea)\b',
 'ownership':r'\b(shareholding|insider|acquisition|consortium|expression of interest|EOI)\b',
 'disruption':r'\b(shutdown|disruption|strike|outage)\b',
}

def sentence_slices(text):
    # Splitting decimal dots would corrupt numeric evidence. Retain qualifications.
    boundaries=[0]+[m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=[A-Z])',text)]+[len(text)]
    for start,end in zip(boundaries,boundaries[1:]):
        raw=text[start:end]; leading=len(raw)-len(raw.lstrip())
        quote=raw.strip()
        if quote: yield start+leading,quote

def labels(quote, official=False):
    if re.search(r'\b(rumou?r|unconfirmed|reportedly|sources said)\b',quote,re.I): kind='rumor'
    elif re.search(r'\b(expect[s]?|forecast[s]?|guidance|project[s]?|anticipat\w*|aim[s]?|plan[s]?)\b',quote,re.I): kind='guidance'
    elif re.search(r'\b(said|according to|management|spokesperson|believes?)\b',quote,re.I): kind='management_claim'
    elif official: kind='reported_fact'
    else: kind='commentary'  # Publisher prose is not certified by a keyword match.
    event=next((key for key,pattern in EVENT_TERMS.items() if re.search(pattern,quote,re.I)),None)
    if re.search(r'\b(cancelled|canceled|terminated)\b',quote,re.I): lifecycle='cancelled'
    elif re.search(r'\b(EOI|expression of interest|due diligence|proposed|subject to|no binding commitment)\b',quote,re.I): lifecycle='proposed'
    elif re.search(r'\b(completed|commissioned|operational)\b',quote,re.I): lifecycle='completed'
    elif re.search(r'\bapproved\b',quote,re.I) and not re.search(r'\b(not|pending) approved\b',quote,re.I): lifecycle='approved'
    elif re.search(r'\b(announced|declared)\b',quote,re.I): lifecycle='announced'
    else: lifecycle='unknown'
    return kind,event,lifecycle

def validate_candidate(candidate, sections, subjects, *, official=False):
    section=sections.get(candidate.section_id)
    if section is None or candidate.quote not in section.text: raise ValueError('quote_not_in_source')
    if candidate.subject_key not in subjects: raise ValueError('unlinked_statement_subject')
    ruled_kind,_,ruled_phase=labels(candidate.quote,official)
    if ruled_kind in ('rumor','guidance','management_claim') and candidate.kind=='reported_fact':
        raise ValueError('claim_promoted_to_fact')
    if not official and candidate.kind=='reported_fact': raise ValueError('secondary_fact_requires_review')
    if ruled_phase=='proposed' and candidate.lifecycle in ('approved','effective','completed'):
        raise ValueError('proposed_event_promoted')
    if candidate.attribution and candidate.attribution not in candidate.quote: raise ValueError('attribution_not_in_quote')
    if candidate.sentiment:
        if candidate.sentiment.subject_key!=candidate.subject_key or candidate.sentiment.quote not in candidate.quote:
            raise ValueError('unsupported_sentiment')
    return section

def extract(db,document_id, *, model_output=None):
    document=db.get(Document,document_id)
    parts={s.id:s for s in db.scalars(select(DocumentSection).where(DocumentSection.document_id==document_id))}
    linked=list(db.scalars(select(Instrument.symbol).join(DocumentEntityLink,DocumentEntityLink.instrument_id==Instrument.id)
        .where(DocumentEntityLink.document_id==document_id,DocumentEntityLink.status=='validated')))
    # No company link is invented for sector/macro documents.
    subjects=set(linked or ['market'])
    official=document.document_type in ('annual_report','quarterly_report','announcement','macro_report','policy_document') and document.source_tier<=2
    candidates=[]
    if model_output is not None:
        candidates=StatementBatch.model_validate(model_output).statements
    else:
        for section in parts.values():
            for _,quote in sentence_slices(section.text):
                kind,event,phase=labels(quote,official)
                if not event or len(quote)>6000: continue
                # Multiple mentioned companies are ambiguous; leave attribution
                # at market level unless the literal issuer name is in the quote.
                for subject in subjects:
                    if len(subjects)>1 and subject not in quote: continue
                    candidates.append(StatementCandidate(section_id=section.id,subject_key=subject,quote=quote,
                        kind=kind,event_type=event,lifecycle=phase,topics=classify_news(quote)['topics'],attribution=None,sentiment=None))
    # Validate the whole batch before any writes: one bad candidate must not
    # leave a partially accepted provider response.
    for candidate in candidates:
        validate_candidate(candidate,parts,subjects,official=official)
    saved=[]
    for candidate in candidates:
        section=validate_candidate(candidate,parts,subjects,official=official)
        digest=fingerprint([candidate.subject_key,candidate.quote,candidate.kind,candidate.lifecycle])
        row=db.scalar(select(EvidenceStatement).where(EvidenceStatement.document_id==document_id,
            EvidenceStatement.extractor_version==VERSION,EvidenceStatement.fingerprint==digest))
        if row: saved.append(row.id); continue
        # Rule-extracted text is usable evidence, not inferred financial SQL.
        row=EvidenceStatement(document_id=document_id,subject_type='instrument' if candidate.subject_key!='market' else 'market',
            subject_key=candidate.subject_key,text=candidate.quote,kind=candidate.kind,event_type=candidate.event_type,
            lifecycle=candidate.lifecycle,topics=candidate.topics,attribution=candidate.attribution,
            sentiment=candidate.sentiment.model_dump() if candidate.sentiment else {'direction':'unknown','reason':'not_assessed'},
            method='model' if model_output else 'rules',extractor_version=VERSION,fingerprint=digest,
            validation_status='validated' if not model_output else 'needs_review')
        db.add(row);db.flush()
        start=section.text.index(candidate.quote)
        db.add(StatementEvidence(statement_id=row.id,section_id=section.id,quote=candidate.quote,
            start_offset=start,end_offset=start+len(candidate.quote),locator={'page_number':section.page_number,
                'section_start_offset':section.start_offset,'parser_version':section.parser_version}))
        saved.append(row.id)
    db.flush();return saved
