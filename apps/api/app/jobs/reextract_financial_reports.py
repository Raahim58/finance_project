"""Bounded source-pinned financial replay. Dry-run first; existing facts are retained for audit."""
import argparse
from datetime import date
from decimal import Decimal
import hashlib
import json
from sqlalchemy import select
from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.artifact_store import get_artifact_store
from app.models.document import Document
from app.models.workstation import FinancialFact, SourceArtifact
from app.providers.fundamentals.extraction import FINANCIAL_EXTRACTION_VERSION, explicit_report_period, extract_facts, parse_financial_pdf


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',action='append',required=True)
    parser.add_argument('--limit',type=int,default=2)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not 1<=args.limit<=10:parser.error('Limit must be 1..10')
    with SessionLocal() as db:
        documents=list(db.scalars(select(Document).where(Document.symbol.in_([value.upper() for value in args.symbol]),
            Document.visibility=='public',Document.data_status=='observed',Document.published_date<=date.today(),
            Document.document_type.in_(('annual_report','quarterly_report','interim_report')))
            .order_by(Document.published_date.desc(),Document.id).limit(args.limit)))
        for doc in documents:
            artifact=db.get(SourceArtifact,doc.artifact_id) if doc.artifact_id else None
            if not artifact or not artifact.storage_path:raise ValueError('Source artifact unavailable')
            content=get_artifact_store(settings).get(artifact.storage_path)
            if hashlib.sha256(content).hexdigest()!=artifact.sha256 or doc.content_hash!=artifact.sha256:
                raise ValueError('Source hash mismatch')
            if args.apply:
                from app.jobs.phase2_tasks import financial_extract
                result=financial_extract(doc.id)
                print(json.dumps({'symbol':doc.symbol,'document_id':doc.id,'source_url':doc.source_url,'result':result},default=str),flush=True)
                continue
            pages,classification,notes=parse_financial_pdf(content)
            period=explicit_report_period(pages,doc.title)
            facts,diagnostics=extract_facts(pages,period,extraction_method='ocr' if classification=='ocr' else 'text_layout',
                confidence=Decimal('.7') if classification=='ocr' else Decimal('.9'),strict=True) if period else ([],['Source period unavailable'])
            old=list(db.scalars(select(FinancialFact).where(FinancialFact.document_id==doc.id)))
            print(json.dumps({'symbol':doc.symbol,'document_id':doc.id,'source_url':doc.source_url,'source_hash':artifact.sha256,
                'installed_version':FINANCIAL_EXTRACTION_VERSION,'previous_version':doc.extraction_version,
                'old_active_facts':sum(row.confidence is None or row.confidence>0 for row in old),'parsed_facts':len(facts),
                'classification':classification,'diagnostics':[*(notes[:5]),*(diagnostics[:10])],
                'unit_headers':[(page.page_number,line.strip()) for page in pages for line in page.text.splitlines()
                    if any(word in line.lower() for word in ('rupees','pkr','million',"'000"))][:12]},default=str),flush=True)


if __name__=='__main__':main()
