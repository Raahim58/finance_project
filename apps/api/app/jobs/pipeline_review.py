"""Explicit operator review; quote validation cannot prove interpretation."""
import argparse
import getpass
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.pipeline import EvidenceStatement,ServiceCredential,IngestionStageRun,SourceTarget
from app.models.workstation import Instrument
from app.core.security import encrypt_secret
from app.services.pipeline.runs import enqueue


def review_statement(db,identifier,accept):
    row=db.get(EvidenceStatement,identifier)
    if not row or row.validation_status!='needs_review': raise ValueError('reviewable_statement_not_found')
    row.validation_status='validated' if accept else 'rejected'
    # Review refreshes only the affected issuer, including withdrawn evidence.
    inst=db.scalar(select(Instrument).where(Instrument.symbol==row.subject_key))
    if inst:
        enqueue(db,'intelligence','instrument:'+inst.id,{'instrument_id':inst.id,'reviewed_statement':row.id,'status':row.validation_status})
    db.commit();return {'statement_id':row.id,'status':row.validation_status}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--accept');group.add_argument('--reject');group.add_argument('--credential',choices=['pipeline_enrichment','tavily_discovery'])
    group.add_argument('--secondary-symbol');group.add_argument('--enqueue-enrichment');group.add_argument('--tavily-target');
    parser.add_argument('--sections',nargs='+',default=[])
    parser.add_argument('--public-nonpersonal',action='store_true')
    parser.add_argument('--query')
    parser.add_argument('--domains',nargs='+',default=[])
    group.add_argument('--retry-run');group.add_argument('--enable-target');group.add_argument('--disable-target')
    args=parser.parse_args()
    with SessionLocal() as db:
        if args.secondary_symbol:
            inst=db.scalar(select(Instrument).where(Instrument.symbol==args.secondary_symbol.upper()))
            if not inst: parser.error('Observed issuer required')
            row=enqueue(db,'secondary_tables','secondary:'+inst.id,{'symbol':inst.symbol})
            db.commit();print(json.dumps({'run_id':row.id,'status':row.status}));return
        if args.enqueue_enrichment:
            if not args.public_nonpersonal or not args.sections: parser.error('Review nonpersonal source sections and supply --public-nonpersonal --sections')
            from app.models.document import Document
            from app.models.pipeline import DocumentEntityLink
            doc=db.get(Document,args.enqueue_enrichment)
            if not doc or doc.visibility!='public' or doc.owner_user_id or doc.portfolio_id: parser.error('Public company-only document required')
            subjects=list(db.scalars(select(Instrument.symbol).join(DocumentEntityLink,DocumentEntityLink.instrument_id==Instrument.id).where(DocumentEntityLink.document_id==doc.id))) or ['market']
            row=enqueue(db,'enrich','document:'+doc.id,{'document_id':doc.id,'section_ids':args.sections[:8],'subjects':subjects,'public_nonpersonal':True})
            db.commit();print(json.dumps({'run_id':row.id,'status':row.status}));return
        if args.tavily_target:
            row=db.get(SourceTarget,args.tavily_target)
            if not row or row.adapter_key!='tavily' or not args.query or not args.domains: parser.error('Tavily target, query and approved domains required')
            row.cursor={**row.cursor,'query':args.query,'domains':args.domains[:20]};db.commit()
            print(json.dumps({'target_id':row.id,'configured':True}));return
        if args.credential:
            secret=getpass.getpass('Application API key (hidden): ')
            if not secret.strip(): parser.error('Empty key')
            row=db.scalar(select(ServiceCredential).where(ServiceCredential.purpose==args.credential))
            if not row: row=ServiceCredential(purpose=args.credential,provider='openrouter' if args.credential=='pipeline_enrichment' else 'tavily');db.add(row)
            row.secret_encrypted=encrypt_secret(secret.strip());row.active=True;db.commit()
            print(json.dumps({'purpose':args.credential,'saved':True}));return
        if args.accept or args.reject:
            print(json.dumps(review_statement(db,args.accept or args.reject,bool(args.accept))));return
        if args.retry_run:
            row=db.get(IngestionStageRun,args.retry_run)
            if not row or row.status not in ('dead_letter','blocked','needs_review'): parser.error('Run is not reviewable')
            row.status='queued';row.attempt_count=0;row.next_attempt_at=None;row.dispatch_until=None;db.commit()
            print('{"status":"queued"}');return
        if args.enable_target or args.disable_target:
            row=db.get(SourceTarget,args.enable_target or args.disable_target)
            if not row: parser.error('Target not found')
            row.enabled=bool(args.enable_target);db.commit();print(json.dumps({'id':row.id,'enabled':row.enabled}));return
        rows=db.scalars(select(EvidenceStatement).where(EvidenceStatement.validation_status=='needs_review').limit(50))
        print(json.dumps([{'id':r.id,'subject':r.subject_key,'kind':r.kind,'text':r.text,'sentiment':r.sentiment} for r in rows]))

if __name__=='__main__':main()
