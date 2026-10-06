"""Dictionary links require literal evidence. Ambiguous short aliases are rejected."""
import re
from datetime import date
from sqlalchemy import select, or_
from app.models.workstation import Instrument, InstrumentAlias
from app.models.pipeline import DocumentEntityLink, DocumentSection
from app.models.document import Document, DocumentEvidenceTag


def link(db,document_id):
    document=db.get(Document,document_id)
    parts=list(db.scalars(select(DocumentSection).where(DocumentSection.document_id==document_id)))
    instruments=list(db.scalars(select(Instrument)))
    aliases={}
    for inst in instruments:
        for value,method in ((inst.name,'company_name'),(inst.symbol,'ticker')):
            aliases.setdefault(value,[]).append((inst,method))
    effective=document.published_date or date.today()
    for alias in db.scalars(select(InstrumentAlias).where(
        or_(InstrumentAlias.valid_from.is_(None),InstrumentAlias.valid_from<=effective),
        or_(InstrumentAlias.valid_to.is_(None),InstrumentAlias.valid_to>=effective))):
        inst=next((i for i in instruments if i.id==alias.instrument_id),None)
        if inst and len(alias.alias)>=5: aliases.setdefault(alias.alias,[]).append((inst,'alias'))
    linked={r.instrument_id for r in db.scalars(select(DocumentEntityLink).where(DocumentEntityLink.document_id==document_id))}
    tags={t.value for t in db.scalars(select(DocumentEvidenceTag).where(DocumentEvidenceTag.document_id==document_id,DocumentEvidenceTag.kind=='company'))}
    for alias,matches in aliases.items():
        if len({i.id for i,_ in matches})!=1: continue
        inst,method=matches[0]
        if inst.id in linked: continue
        # Common short uppercase words (AIR/NET/GAS) need company-name evidence.
        if method=='ticker' and len(alias)<=3: continue
        flags=0 if method=='ticker' else re.I
        for section in parts:
            match=re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',section.text,flags)
            if not match: continue
            db.add(DocumentEntityLink(document_id=document_id,instrument_id=inst.id,role='mentioned',method=method,
                section_id=section.id,support_quote=match.group(),status='validated'))
            if inst.symbol not in tags:
                db.add(DocumentEvidenceTag(document_id=document_id,kind='company',value=inst.symbol,basis='literal_entity_link'))
                tags.add(inst.symbol)
            linked.add(inst.id); break
    db.flush()
    return sorted(linked)
