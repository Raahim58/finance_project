"""Financial source review and company evidence freshness stay independent."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.user import User
from app.models.workstation import FinancialFact, Instrument, StandardizedFinancialFact
from app.services.company_snapshot import dependency_hash, financial_rows
from app.services.context_builder import ContextBuilder
from app.services.research_intelligence_service import exact_facts
from app.schemas.intelligence_context import IntelligenceContextRequest, ContextScope, ContextSectionName
from app.tools.research_tools import CompanyDigestInput, _company_digest
from app.tools.registry import expand_model_data

pytestmark = pytest.mark.usefixtures("database")


def instrument(db):
    row=Instrument(symbol='TEST',name='Fixture Company',sector='Cement')
    db.add(row);db.flush();return row


@pytest.mark.parametrize('quality',['observed','validated'])
def test_legacy_secondary_cannot_become_verified_by_quality_label_alone(quality):
    with SessionLocal() as db:
        company=instrument(db)
        raw=StandardizedFinancialFact(instrument_id=company.id,metric='revenue',period_type='annual',
            period_key='2025',period_end=date(2025,12,31),value=Decimal('123'),unit='PKR million',
            source='scstrade',source_url='https://example.com/secondary',quality_status=quality)
        db.add(raw);db.flush()
        assert financial_rows(db,company)==[]
        assert exact_facts(db,company)==[]
        section,_=ContextBuilder._company_facts(db,None,None,company)
        assert section.data['fundamentals']==[]
        gap,=section.data['financial_evidence_gaps']
        assert gap['code']=='unverified_secondary_financials' and gap['row_count']==1
        assert 'accounting_basis' in gap['missing'] and 'verified_fiscal_period' in gap['missing']
        assert raw.period_end==date(2025,12,31) and raw.value==Decimal('123') and raw.quality_status==quality


def document(db,company,**changes):
    row=Document(document_type='annual_report',symbol=company.symbol,title='Fixture filing',
        source_name='Original Publisher',source_url='https://example.com/report',content_hash='body-version',
        published_date=date(2025,8,1),**changes)
    db.add(row);db.flush();return row


@pytest.mark.parametrize('field,value',[
    ('status','revoked'),('data_status','excluded_irrelevant'),('document_type','commentary'),
    ('source_name','Corrected Publisher'),('source_tier',4),('source_url','https://example.com/corrected'),
    ('visibility','private'),
])
def test_source_metadata_changes_invalidate_snapshot_even_when_body_is_unchanged(field,value):
    with SessionLocal() as db:
        company=instrument(db);doc=document(db,company)
        previous=dependency_hash(db,company)
        setattr(doc,field,value);db.flush()
        assert doc.content_hash=='body-version'
        assert dependency_hash(db,company)!=previous


def test_owner_change_invalidates_snapshot_and_public_exact_readers():
    with SessionLocal() as db:
        company=instrument(db);doc=document(db,company)
        user=User(email='source-owner@example.com',password_hash='unused');db.add(user);db.flush()
        db.add(FinancialFact(instrument_id=company.id,taxonomy_key='revenue',period_type='annual',
            period_start=date(2024,7,1),period_end=date(2025,6,30),value=Decimal('100'),
            unit='PKR',currency='PKR',document_id=doc.id,consolidated=True))
        db.flush();previous=dependency_hash(db,company)
        assert financial_rows(db,company) and exact_facts(db,company)
        builder=ContextBuilder()
        request=IntelligenceContextRequest(symbol=company.symbol,scope=ContextScope.COMPANY_INTELLIGENCE,
            sections=(ContextSectionName.COMPANY_FACTS,))
        before=builder.build(db,user,request)
        assert before.sections['company_facts'].data['fundamentals']
        doc.owner_user_id=user.id;db.flush()
        assert dependency_hash(db,company)!=previous
        assert financial_rows(db,company)==[] and exact_facts(db,company)==[]
        assert ContextBuilder._company_facts(db,None,None,company)[0].data['fundamentals']==[]
        after=builder.build(db,user,request)
        assert after.sections['company_facts'].data['fundamentals']==[]
        assert after.sections['company_facts'].dependency_hash!=before.sections['company_facts'].dependency_hash


def test_old_relevant_source_outside_first_hundred_still_invalidates_snapshot():
    with SessionLocal() as db:
        company=instrument(db);old=document(db,company)
        for index in range(101):
            db.add(Document(document_type='news',symbol=company.symbol,title=f'Fixture article {index}',
                source_name='Publisher',source_url=f'https://example.com/{index}',content_hash=str(index),
                published_date=date(2026,10,1)))
        db.flush();previous=dependency_hash(db,company)
        old.status='revoked';db.flush()
        assert dependency_hash(db,company)!=previous


def saved_fixture(snapshot=None,prepared=None):
    return {'snapshot':snapshot,'prepared_intelligence':prepared or [],'input_hash':'current',
        'status':'source_grounded','brief_is_current':False,'brief_validation_status':'reference_only'}


def prepared_section(key,*,state='source_grounded'):
    statement = ('The Board proposed an interim dividend, subject to approval. '
                 if key == 'dividends' else '')+'Source qualification must survive.'
    return {'section':key,'state':state,'content':{'evidence':[{'statement_id':'statement-'+key,
        'text':statement}]} if state=='source_grounded' else {},
        'sources':[{'statement_id':'statement-'+key,'source_url':'https://example.com/original',
            'source_name':'Original Publisher','title':'Original Article'}] if state=='source_grounded' else [],
        'gaps':['Evidence dependency changed.'] if state=='stale' else []}


def stub_rebuild(monkeypatch,prepared):
    """Stale public sections are rebuilt from retained evidence; stub that with no corpus."""
    calls=[]
    monkeypatch.setattr('app.services.pipeline.intelligence.refresh',lambda _db,instrument_id:calls.append(instrument_id))
    monkeypatch.setattr('app.services.pipeline.intelligence.read',lambda _db,_instrument_id:prepared)
    return calls


@pytest.mark.parametrize('snapshot_hash',['old','current'])
def test_pipeline_uses_prepared_evidence_instead_of_legacy_snapshot(monkeypatch,snapshot_hash):
    from app.services import company_digest_service
    monkeypatch.setattr(settings,'pipeline_enabled',True)
    saved=saved_fixture({'input_hash':snapshot_hash,'legacy_wrong_claim':'DO NOT REUSE'},
        [prepared_section('dividends'),prepared_section('risks',state='stale')])
    monkeypatch.setattr(company_digest_service,'read_digest',lambda *_args,**_kwargs:saved)
    rebuilt=stub_rebuild(monkeypatch,saved['prepared_intelligence'])
    with SessionLocal() as db:
        company=instrument(db)
        result=_company_digest(db,SimpleNamespace(id='fixture-user'),CompanyDigestInput(instrument_id=company.id,sections=['dividends']))
        data=expand_model_data(result['data'])
        assert rebuilt==[company.id]  # a stale section triggers one deterministic rebuild, no fetch
        assert result['status']=='ok' and 'DO NOT REUSE' not in str(result)
        assert [section['section'] for section in data['prepared_intelligence']]==['dividends']
        assert data['available_sections']==['dividends']
        assert data['unavailable_sections'][0]['state']=='stale'
        assert data['prepared_intelligence'][0]['content']['evidence'][0]['text']==prepared_section('dividends')['content']['evidence'][0]['text']


def test_stale_snapshot_without_prepared_data_is_withheld(monkeypatch):
    from app.services import company_digest_service
    monkeypatch.setattr(company_digest_service,'read_digest',lambda *_args,**_kwargs:
        saved_fixture({'input_hash':'old','legacy_wrong_claim':'DO NOT REUSE'}))
    with SessionLocal() as db:
        company=instrument(db)
        result=_company_digest(db,SimpleNamespace(id='fixture-user'),CompanyDigestInput(instrument_id=company.id))
        assert result['status']=='missing' and result['sources']==[]
        assert 'DO NOT REUSE' not in str(result)
        assert expand_model_data(result['data'])['status']=='stale'


def test_unusable_requested_sections_trigger_detail_fallback_without_hiding_other_availability(monkeypatch):
    from app.services import company_digest_service
    monkeypatch.setattr(settings,'pipeline_enabled',True)
    monkeypatch.setattr(company_digest_service,'read_digest',lambda *_args,**_kwargs:
        saved_fixture(prepared=[prepared_section('dividends',state='stale'),prepared_section('risks')]))
    stub_rebuild(monkeypatch,[prepared_section('dividends',state='stale'),prepared_section('risks')])
    with SessionLocal() as db:
        company=instrument(db)
        result=_company_digest(db,SimpleNamespace(id='fixture-user'),CompanyDigestInput(instrument_id=company.id,sections=['dividends']))
        data=expand_model_data(result['data'])
        assert result['status']=='missing' and result['sources']==[]
        assert data['prepared_intelligence'][0]['state']=='stale'
        assert data['omitted_available_sections']==['risks'] and data['detail_tools']


@pytest.mark.parametrize('basis,expected',[('',0),('Consolidated ',2)])
def test_legacy_report_ingestion_requires_basis_and_preserves_duration(monkeypatch,basis,expected):
    from app.providers.fundamentals.psx_financials import PsxFinancialsProvider, ReportCatalogItem
    from app.services import ingestion_service, rag_service
    from app.services.rag_service import ParsedPage
    item=ReportCatalogItem('TEST','annual','June 30, 2025',date(2025,8,1),'https://example.com/report.pdf','fixture')
    monkeypatch.setattr(PsxFinancialsProvider,'fetch_company_catalog',lambda *_args:[item])
    monkeypatch.setattr(PsxFinancialsProvider,'fetch_report',lambda *_args:b'fixture-report')
    monkeypatch.setattr(ingestion_service,'store_artifact',lambda *_args,**_kwargs:SimpleNamespace(id=None))
    monkeypatch.setattr(rag_service,'parse_pdf',lambda *_args:[ParsedPage(1,
        basis+'Statement of Profit or Loss\nYear ended June 30, 2025\nPKR million\n2025 2024\nRevenue 100 90')])
    with SessionLocal() as db:
        company=instrument(db)
        result=ingestion_service._refresh_psx_financials(db,symbols=['TEST'],limit=1)
        assert result['accepted']==1 and result['rejected']==0
        facts=list(db.scalars(select(FinancialFact).where(FinancialFact.instrument_id==company.id)))
        assert len(facts)==expected
        if facts:
            assert {(fact.period_start,fact.period_end) for fact in facts}=={
                (date(2024,7,1),date(2025,6,30)),(date(2023,7,1),date(2024,6,30))}
            assert {fact.consolidated for fact in facts}=={True}
            assert {fact.value for fact in facts}=={Decimal('100000000'),Decimal('90000000')}
