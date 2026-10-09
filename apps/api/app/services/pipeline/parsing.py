"""Stable source offsets; HTML has no invented physical page number."""
import re
from sqlalchemy import select
from app.models.document import Document, DocumentPage
from app.models.pipeline import DocumentSection

VERSION='sections-v1'

def sections(db, document_id):
    document=db.get(Document,document_id)
    if not document or document.visibility!='public' or document.owner_user_id or document.portfolio_id:
        raise ValueError('public_document_required')
    existing=list(db.scalars(select(DocumentSection).where(DocumentSection.document_id==document_id,
        DocumentSection.parser_version==VERSION).order_by(DocumentSection.ordinal)))
    if existing: return existing
    is_pdf=document.document_type in ('annual_report','quarterly_report') or (document.source_url or '').lower().endswith('.pdf')
    if document.artifact_id:
        from app.models.workstation import SourceArtifact
        artifact=db.get(SourceArtifact,document.artifact_id)
        is_pdf=is_pdf or bool(artifact and 'pdf' in (artifact.content_type or '').lower())
    ordinal=0; rows=[]
    for page in db.scalars(select(DocumentPage).where(DocumentPage.document_id==document_id).order_by(DocumentPage.page_number)):
        # Break long paragraphs at sentence boundaries; never change quote bytes.
        pattern=r'[^\n]+(?:\n(?!\n)[^\n]+)*'
        for match in re.finditer(pattern,page.text):
            text=match.group().strip()
            if not text: continue
            start=match.start()+len(match.group())-len(match.group().lstrip())
            row=DocumentSection(document_id=document_id,ordinal=ordinal,kind='paragraph',text=text,
                page_number=page.page_number if is_pdf else None,start_offset=start,end_offset=start+len(text),parser_version=VERSION)
            db.add(row); rows.append(row); ordinal+=1
    db.flush()
    return rows
